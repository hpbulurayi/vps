import os
import shutil
import datetime
import zipfile
import tarfile
import json
import string
from flask import Blueprint, render_template, jsonify, request, send_from_directory, current_app
from werkzeug.utils import secure_filename
from .utils import login_required, _get_safe_path, is_admin

file_manager_bp = Blueprint('file_manager', __name__, url_prefix='/file_manager')

@file_manager_bp.route('/')
@login_required
def file_manager_index():
    return render_template('file_manager.html')

@file_manager_bp.route('/files')
@login_required
def list_files():
    """列出指定目录下的文件和文件夹，并包含详细信息。"""
    try:
        req_path = request.args.get('path', '')
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)

        # 当 Windows 管理员访问根目录时，列出所有磁盘驱动器
        if not req_path and os.name == 'nt' and is_admin():
            items = []
            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    items.append({
                        "name": f"磁盘 ({letter}:)",
                        "type": "directory",
                        "path": drive,
                        "size": None,
                        "last_modified": None,
                        "permissions": None
                    })
            return jsonify({
                "items": items,
                "total_pages": 1,
                "current_page": 1,
                "current_full_path": "我的电脑"
            })

        # 针对 Windows 驱动器根路径的特殊处理
        if os.name == 'nt' and req_path.endswith(':\\'):
             _, error_response = _get_safe_path(req_path, check_exists=True, is_dir=True)
             full_path = req_path
        else:
            full_path, error_response = _get_safe_path(req_path, check_exists=True, is_dir=True)
        
        if error_response:
            return error_response

        items = []
        with os.scandir(full_path) as it:
            for entry in it:
                try:
                    stat_info = entry.stat()
                    is_dir = entry.is_dir()
                    
                    items.append({
                        "name": entry.name,
                        "type": "directory" if is_dir else "file",
                        "path": entry.path.replace("\\", "/"),
                        "size": stat_info.st_size,
                        "last_modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                        "permissions": oct(stat_info.st_mode & 0o777)
                    })
                except OSError:
                    # 忽略无法访问的文件或链接
                    continue
        
        # 分页处理
        total_items = len(items)
        total_pages = (total_items + page_size - 1) // page_size
        start = (page - 1) * page_size
        end = start + page_size
        paginated_items = items[start:end]

        # 添加 ".." 返回上一级
        # 确定是否在根目录
        is_root_path = (not is_admin() and full_path == current_app.config['FILE_MANAGER_ROOT']) or \
                       (is_admin() and not req_path and os.name == 'nt') or \
                       (is_admin() and full_path == os.path.abspath('/'))

        if not is_root_path:
            # 对于 Windows 驱动器根目录，返回到空路径以显示所有驱动器
            if os.name == 'nt' and is_admin() and len(full_path) == 3 and full_path.endswith(':\\'):
                parent_path = ''
            else:
                parent_path = os.path.dirname(full_path).replace("\\", "/")

            paginated_items.insert(0, {
                "name": "..",
                "type": "directory",
                "path": parent_path,
                "size": None,
                "last_modified": None,
                "permissions": None
            })

        return jsonify({
            "items": paginated_items,
            "total_pages": total_pages,
            "current_page": page,
            "current_full_path": full_path.replace("\\", "/")
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/download')
@login_required
def download_file():
    """下载指定的文件。"""
    try:
        req_path = request.args.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, check_file=True)
        if error_response:
            return error_response

        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path), as_attachment=True)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/delete', methods=['POST'])
@login_required
def delete_file():
    """删除指定的文件或文件夹。"""
    try:
        req_path = request.json.get('path', '')
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True)
        if error_response:
            return error_response

        if os.path.isfile(full_path):
            os.remove(full_path)
        elif os.path.isdir(full_path):
            shutil.rmtree(full_path)
        
        return jsonify({"status": "success", "message": f"Successfully deleted {req_path}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/batch-delete', methods=['POST'])
@login_required
def batch_delete_files():
   """批量删除文件或文件夹。"""
   try:
       paths = request.json.get('paths', [])
       if not paths:
           return jsonify({"status": "error", "message": "未提供要删除的路径。"}), 400

       success_count = 0
       errors = []

       for path in paths:
           try:
               full_path, error_response = _get_safe_path(path, check_exists=True)
               if error_response:
                   errors.append(f"路径 '{path}' 无效或无权限。")
                   continue

               if os.path.isfile(full_path):
                   os.remove(full_path)
                   success_count += 1
               elif os.path.isdir(full_path):
                   shutil.rmtree(full_path)
                   success_count += 1
           except Exception as e:
               errors.append(f"删除 '{path}' 失败: {str(e)}")

       message = f"成功删除 {success_count} 个项目。"
       if errors:
           message += f" {len(errors)} 个项目删除失败。详情: " + "; ".join(errors)
           return jsonify({"status": "partial_success", "message": message, "errors": errors})
       
       return jsonify({"status": "success", "message": message})

   except Exception as e:
       return jsonify({"status": "error", "message": f"批量删除操作期间发生意外错误: {str(e)}"}), 500

def _handle_file_operation(operation, sources, destination):
   """
   辅助函数，用于处理文件/文件夹的复制或移动操作。
   :param operation: 'copy' 或 'move'
   :param sources: 源路径列表
   :param destination: 目标目录路径
   """
   success_count = 0
   errors = []

   # 1. 验证目标路径
   dest_full_path, error_response = _get_safe_path(destination, check_exists=True, is_dir=True)
   if error_response:
       return jsonify({"status": "error", "message": f"无效的目标路径: {destination}"}), 500

   for src_rel_path in sources:
       try:
           # 2. 验证源路径
           src_full_path, error_response = _get_safe_path(src_rel_path, check_exists=True)
           if error_response:
               errors.append(f"源路径 '{src_rel_path}' 无效或无权限。")
               continue

           # 3. 构建最终的目标路径
           base_name = os.path.basename(src_full_path)
           final_dest_path = os.path.join(dest_full_path, base_name)

           # 4. 检查目标路径是否已存在
           if os.path.exists(final_dest_path):
               errors.append(f"目标路径 '{final_dest_path.replace(os.path.sep, '/')}' 已存在。")
               continue
           
           # 5. 执行操作
           if operation == 'copy':
               if os.path.isdir(src_full_path):
                   shutil.copytree(src_full_path, final_dest_path)
               else:
                   shutil.copy2(src_full_path, final_dest_path)
           elif operation == 'move':
               shutil.move(src_full_path, final_dest_path)
           
           success_count += 1

       except Exception as e:
           errors.append(f"处理 '{src_rel_path}' 时出错: {str(e)}")

   message = f"成功{operation}了 {success_count} 个项目到 '{destination}'。"
   if errors:
       message += f" {len(errors)} 个项目失败。详情: " + "; ".join(errors)
       return jsonify({"status": "partial_success", "message": message, "errors": errors})
   
   return jsonify({"status": "success", "message": message})


@file_manager_bp.route('/files/copy', methods=['POST'])
@login_required
def copy_files():
   """复制一个或多个文件/文件夹到指定位置。"""
   sources = request.json.get('sources', [])
   destination = request.json.get('destination', '')
   return _handle_file_operation('copy', sources, destination)


@file_manager_bp.route('/files/move', methods=['POST'])
@login_required
def move_files():
   """移动一个或多个文件/文件夹到指定位置。"""
   sources = request.json.get('sources', [])
   destination = request.json.get('destination', '')
   return _handle_file_operation('move', sources, destination)

@file_manager_bp.route('/files/upload', methods=['POST'])
@login_required
def upload_file():
    """上传文件到指定目录。"""
    try:
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No file part"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"status": "error", "message": "No selected file"}), 400

        req_path = request.form.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, is_dir=True)
        if error_response:
            return error_response

        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(full_path, filename))
            return jsonify({"status": "success", "message": f"File {filename} uploaded successfully to {req_path}"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/create_folder', methods=['POST'])
@login_required
def create_folder():
    """创建新文件夹。"""
    try:
        req_path = request.json.get('path', '')
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400
            
        full_path, error_response = _get_safe_path(req_path)
        if error_response:
            return error_response

        if os.path.exists(full_path):
            return jsonify({"status": "error", "message": "Path already exists."}), 400

        os.makedirs(full_path)
        return jsonify({"status": "success", "message": f"Folder '{req_path}' created successfully."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/rename', methods=['POST'])
@login_required
def rename_file():
    """重命名文件或文件夹。"""
    try:
        old_path_rel = request.json.get('old_path', '')
        new_path_rel = request.json.get('new_path', '')

        if not old_path_rel or not new_path_rel:
            return jsonify({"status": "error", "message": "Old and new paths are required."}), 400

        old_full_path, error_response = _get_safe_path(old_path_rel, check_exists=True)
        if error_response:
            return error_response
            
        new_full_path, error_response = _get_safe_path(new_path_rel)
        if error_response:
            return error_response

        if os.path.exists(new_full_path):
            return jsonify({"status": "error", "message": "New path already exists."}), 400
        
        os.rename(old_full_path, new_full_path)
        return jsonify({"status": "success", "message": f"Renamed '{old_path_rel}' to '{new_path_rel}'."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/get_content', methods=['GET'])
@login_required
def get_file_content():
    """获取文本文件内容。"""
    try:
        req_path = request.args.get('path', '')
        full_path, error_response = _get_safe_path(req_path, check_exists=True, check_file=True)
        if error_response:
            return error_response
        
        file_size = os.path.getsize(full_path)
        max_preview_size = 1 * 1024 * 1024 

        truncated = file_size > max_preview_size
        read_size = max_preview_size if truncated else file_size

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read(read_size)
        except UnicodeDecodeError:
            try:
                with open(full_path, 'r', encoding='latin-1') as f:
                    content = f.read(read_size)
            except Exception:
                return jsonify({"status": "error", "message": "无法解码文件内容，请尝试其他方式。"}), 500
        
        if truncated:
            content += f"\n\n... (文件过大，仅显示前 {max_preview_size // 1024}KB 内容) ..."

        return jsonify({"status": "success", "content": content, "truncated": truncated})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/save_content', methods=['POST'])
@login_required
def save_file_content():
    """保存文本文件内容。"""
    try:
        req_path = request.json.get('path', '')
        content = request.json.get('content', '')
        
        full_path, error_response = _get_safe_path(req_path)
        if error_response:
            return error_response
            
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({"status": "success", "message": f"文件 '{req_path}' 保存成功。"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/permissions', methods=['GET', 'POST'])
@login_required
def handle_permissions():
    """获取或设置文件/文件夹权限。"""
    try:
        req_path = request.args.get('path') if request.method == 'GET' else request.json.get('path')
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True)
        if error_response:
            return error_response

        if request.method == 'GET':
            current_mode = os.stat(full_path).st_mode
            octal_permission = oct(current_mode & 0o777)
            return jsonify({"status": "success", "path": req_path, "permissions": octal_permission})
        elif request.method == 'POST':
            new_permission_octal = request.json.get('permissions')
            if not new_permission_octal:
                return jsonify({"status": "error", "message": "Permissions are required."}), 400
            
            try:
                mode_int = int(new_permission_octal, 8)
                os.chmod(full_path, mode_int)
                return jsonify({"status": "success", "message": f"权限已更新为 {new_permission_octal}。"}), 200
            except ValueError:
                return jsonify({"status": "error", "message": "无效的权限格式。请提供有效的八进制数 (例如 755)。"}), 400
            except Exception as e:
                return jsonify({"status": "error", "message": f"设置权限失败: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/compress', methods=['POST'])
@login_required
def compress_file_or_folder():
    """压缩文件或文件夹。"""
    try:
        req_path = request.json.get('path', '')
        archive_format = request.json.get('format', 'zip')
        
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True)
        if error_response:
            return error_response

        output_filename = os.path.basename(full_path)
        output_dir = os.path.dirname(full_path)

        if os.path.isfile(full_path):
            if archive_format == 'zip':
                archive_name = os.path.join(output_dir, f"{output_filename}.zip")
                with zipfile.ZipFile(archive_name, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(full_path, os.path.basename(full_path))
            elif archive_format == 'tar.gz':
                archive_name = os.path.join(output_dir, f"{output_filename}.tar.gz")
                with tarfile.open(archive_name, "w:gz") as tar:
                    tar.add(full_path, arcname=os.path.basename(full_path))
            else:
                return jsonify({"status": "error", "message": "不支持的压缩格式。"}), 400
        elif os.path.isdir(full_path):
            if archive_format == 'zip':
                archive_name = os.path.join(output_dir, output_filename)
                shutil.make_archive(archive_name, 'zip', full_path)
                archive_name = f"{output_filename}.zip"
            elif archive_format == 'tar.gz':
                archive_name = os.path.join(output_dir, output_filename)
                shutil.make_archive(archive_name, 'gztar', full_path)
                archive_name = f"{output_filename}.tar.gz"
            else:
                return jsonify({"status": "error", "message": "不支持的压缩格式。"}), 400
        else:
            return jsonify({"status": "error", "message": "无法压缩非文件或文件夹的路径。"}), 400
        
        return jsonify({"status": "success", "message": f"'{req_path}' 已成功压缩为 '{os.path.basename(archive_name)}'。"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@file_manager_bp.route('/files/decompress', methods=['POST'])
@login_required
def decompress_file():
    """解压文件。"""
    try:
        req_path = request.json.get('path', '')
        destination = request.json.get('destination', '')
        
        if not req_path:
            return jsonify({"status": "error", "message": "Path is required."}), 400

        full_path, error_response = _get_safe_path(req_path, check_exists=True, check_file=True)
        if error_response:
            return error_response

        if destination:
            full_destination, error_response = _get_safe_path(destination, check_exists=True, is_dir=True)
            if error_response:
                return error_response
        else:
            full_destination = os.path.dirname(full_path)

        os.makedirs(full_destination, exist_ok=True)

        if zipfile.is_zipfile(full_path):
            with zipfile.ZipFile(full_path, 'r') as zf:
                zf.extractall(full_destination)
        elif tarfile.is_tarfile(full_path):
            with tarfile.open(full_path, 'r:*') as tar:
                tar.extractall(full_destination)
        else:
            return jsonify({"status": "error", "message": "不支持的解压文件格式。"}), 400
        
        return jsonify({"status": "success", "message": f"'{req_path}' 已成功解压到 '{destination if destination else os.path.basename(full_destination)}'。"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
@file_manager_bp.route('/files/search')
@login_required
def search_files():
    """在指定路径下递归搜索文件和文件夹。"""
    try:
        query = request.args.get('query', '').strip()
        search_path = request.args.get('path', '')
        
        if not query:
            return jsonify({"status": "error", "message": "Search query is required."}), 400

        full_path, error_response = _get_safe_path(search_path, check_exists=True, is_dir=True)
        if error_response:
            return error_response

        items = []
        for root, dirs, files in os.walk(full_path):
            # 检查文件名和文件夹名是否匹配查询
            for name in files + dirs:
                if query.lower() in name.lower():
                    try:
                        entry_path = os.path.join(root, name)
                        stat_info = os.stat(entry_path)
                        is_dir = os.path.isdir(entry_path)
                        
                        # 安全检查：确保非管理员无法看到根目录之外的搜索结果
                        if not is_admin():
                            safe_root = current_app.config['FILE_MANAGER_ROOT']
                            if not os.path.abspath(entry_path).startswith(safe_root):
                                continue

                        items.append({
                            "name": name,
                            "type": "directory" if is_dir else "file",
                            "path": entry_path.replace("\\", "/"),
                            "size": stat_info.st_size,
                            "last_modified": datetime.datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                            "permissions": oct(stat_info.st_mode & 0o777)
                        })
                    except (OSError, FileNotFoundError):
                        # 忽略无法访问的文件或损坏的链接
                        continue
        
        return jsonify({
            "items": items,
            "total_pages": 1,
            "current_page": 1,
            "current_full_path": f"在 '{full_path}' 中搜索 '{query}' 的结果",
            "is_search_result": True
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
BOOKMARKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'bookmarks.json')

def _load_bookmarks():
    """从 bookmarks.json 加载书签。"""
    if not os.path.exists(BOOKMARKS_FILE):
        return []
    try:
        with open(BOOKMARKS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return []

def _save_bookmarks(bookmarks):
    """保存书签到 bookmarks.json。"""
    try:
        with open(BOOKMARKS_FILE, 'w', encoding='utf-8') as f:
            json.dump(bookmarks, f, indent=4, ensure_ascii=False)
        return True
    except IOError:
        return False

@file_manager_bp.route('/bookmarks', methods=['GET'])
@login_required
def get_bookmarks():
    """获取所有书签。"""
    bookmarks = _load_bookmarks()
    return jsonify(bookmarks)

@file_manager_bp.route('/bookmarks/add', methods=['POST'])
@login_required
def add_bookmark():
    """添加一个新的书签。"""
    path = request.json.get('path')
    if not path:
        return jsonify({"status": "error", "message": "Path is required."}), 400

    # 安全检查：在添加书签前验证路径是否有效且在允许范围内
    full_path, error_response = _get_safe_path(path, check_exists=True, is_dir=True)
    if error_response:
        return error_response
    
    bookmarks = _load_bookmarks()
    normalized_path = full_path.replace("\\", "/")
    
    if normalized_path not in bookmarks:
        bookmarks.append(normalized_path)
        if _save_bookmarks(bookmarks):
            return jsonify({"status": "success", "message": "Bookmark added."})
        else:
            return jsonify({"status": "error", "message": "Failed to save bookmarks."}), 500
    else:
        return jsonify({"status": "success", "message": "Bookmark already exists."})

@file_manager_bp.route('/bookmarks/delete', methods=['POST'])
@login_required
def delete_bookmark():
    """删除一个书签。"""
    path = request.json.get('path')
    if not path:
        return jsonify({"status": "error", "message": "Path is required."}), 400

    bookmarks = _load_bookmarks()
    normalized_path = path.replace("\\", "/")
    
    if normalized_path in bookmarks:
        bookmarks.remove(normalized_path)
        if _save_bookmarks(bookmarks):
            return jsonify({"status": "success", "message": "Bookmark deleted."})
        else:
            return jsonify({"status": "error", "message": "Failed to save bookmarks."}), 500
    else:
        return jsonify({"status": "error", "message": "Bookmark not found."}), 404
