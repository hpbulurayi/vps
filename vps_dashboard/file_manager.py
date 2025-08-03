import os
import shutil
import datetime
import zipfile
import tarfile
from flask import Blueprint, render_template, jsonify, request, send_from_directory, current_app
from werkzeug.utils import secure_filename
from .utils import login_required, _get_safe_path
import getpass

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

        full_path, error_response = _get_safe_path(req_path, check_exists=True, is_dir=True)
        if error_response:
            return error_response

        items = []
        with os.scandir(full_path) as it:
            for entry in it:
                try:
                    stat_info = entry.stat()
                    is_dir = entry.is_dir()
                    
                    if getpass.getuser() == 'root':
                        base_dir = '/'
                    else:
                        base_dir = current_app.config['FILE_MANAGER_ROOT']

                    try:
                        relative_item_path = os.path.relpath(entry.path, base_dir).replace("\\", "/")
                    except ValueError:
                        relative_item_path = entry.path.replace("\\", "/")

                    items.append({
                        "name": entry.name,
                        "type": "directory" if is_dir else "file",
                        "path": relative_item_path,
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

        base_dir = '/' if getpass.getuser() == 'root' else current_app.config['FILE_MANAGER_ROOT']
        if full_path != base_dir:
            parent_path = os.path.dirname(req_path)
            paginated_items.insert(0, {
                "name": "..",
                "type": "directory",
                "path": parent_path.replace("\\", "/"),
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