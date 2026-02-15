import json
import os
import datetime
import base64
from flask import Flask, request, jsonify, Response
from pymongo import MongoClient
from gridfs import GridFS
from flask_cors import CORS
from bson import ObjectId

app = Flask(__name__)
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB アップロード上限

# MongoDB Connection
MONGO_URI = os.environ.get('MONGO_URI')

# Global client - Don't call server_info() at top level because it blocks Gunicorn boot
if MONGO_URI:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    print("MongoDB Client initialized (MONGO_URI found)")
else:
    # Local fallback or Dummy client to prevent NameError
    client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=2000)
    print("WARNING: MONGO_URI not found. Running with local fallback.")

db = client['lag_switch_pro']
keys_coll = db['keys']
settings_coll = db['settings']
fs = GridFS(db)

def check_db_connection():
    """DB接続を確認（API呼び出し時に随時使用）"""
    try:
        client.admin.command('ping')
        return True
    except Exception as e:
        print(f"Database connection check FAILED: {e}")
        return False

def get_settings():
    """設定情報を取得（なければデフォルトを返す）"""
    settings = settings_coll.find_one({"type": "version"})
    if not settings:
        default_settings = {
            "type": "version",
            "number": "9.0",
            "download_url": "",
            "release_notes": "Database Migrated",
            "force_update": False,
            "released_at": datetime.datetime.now().isoformat()
        }
        try:
            settings_coll.insert_one(default_settings)
        except Exception as e:
            print(f"Failed to insert default settings: {e}")
        return default_settings
    return settings

@app.route('/verify', methods=['POST'])
def verify_key():
    try:
        data = request.json
        key = data.get('key')
        hwid = data.get('hwid')
        
        if not key:
            return jsonify({"valid": False, "message": "Key missing"}), 400

        key_data = keys_coll.find_one({"key": key})
        
        if not key_data:
            return jsonify({"valid": False, "message": "Invalid Key"}), 404
            
        # 期限チェック
        if key_data.get('expiry') != 'lifetime':
            try:
                exp_date = datetime.datetime.fromisoformat(key_data['expiry'])
                if datetime.datetime.now() > exp_date:
                    return jsonify({"valid": False, "message": "Expired"}), 403
            except:
                pass
                
        # HWIDチェック
        hwid_limit = key_data.get('hwid_limit', 1)
        
        if hwid_limit == 'unlimited':
            pass
        elif key_data.get('hwid') is None or key_data.get('hwid') == "":
            # 初回登録
            keys_coll.update_one({"key": key}, {"$set": {"hwid": hwid}})
        elif key_data['hwid'] != hwid:
            return jsonify({"valid": False, "message": "HWID Mismatch"}), 403
            
        return jsonify({
            "valid": True, 
            "expiry": key_data['expiry'],
            "hwid": key_data.get('hwid', 'unlimited')
        })
    except Exception as e:
        print(f"Error in verify_key: {e}")
        return jsonify({"valid": False, "message": f"Server DB Error: {str(e)}"}), 500

@app.route('/admin/add_key', methods=['POST'])
def add_key():
    try:
        data = request.json
        key = data.get('key')
        expiry = data.get('expiry', 'lifetime')
        hwid_limit = data.get('hwid_limit', 1)
        
        if not key:
            return jsonify({"success": False, "message": "Key name required"}), 400

        if keys_coll.find_one({"key": key}):
            return jsonify({"success": False, "message": "Key exists"}), 400
        
        keys_coll.insert_one({
            "key": key,
            "expiry": expiry,
            "hwid": None,
            "hwid_limit": hwid_limit,
            "created_at": datetime.datetime.now().isoformat()
        })
        return jsonify({"success": True, "message": "Key added"})
    except Exception as e:
        print(f"Error in add_key: {e}")
        return jsonify({"success": False, "message": f"Database Error: {str(e)}"}), 500

@app.route('/admin/delete_key', methods=['POST'])
def delete_key():
    try:
        data = request.json
        key = data.get('key')
        
        result = keys_coll.delete_one({"key": key})
        if result.deleted_count > 0:
            return jsonify({"success": True})
        return jsonify({"success": False, "message": "Key not found"}), 404
    except Exception as e:
        print(f"Error in delete_key: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/admin/reset_hwid', methods=['POST'])
def reset_hwid():
    try:
        data = request.json
        key = data.get('key')
        
        result = keys_coll.update_one({"key": key}, {"$set": {"hwid": None}})
        if result.matched_count > 0:
            return jsonify({"success": True})
        return jsonify({"success": False}), 404
    except Exception as e:
        print(f"Error in reset_hwid: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/admin/list_keys', methods=['GET'])
def list_keys():
    try:
        # 全キーを辞書形式で返す（既存のクライアントとの互換性のため）
        keys = {}
        for k in keys_coll.find():
            keys[k['key']] = {
                "expiry": k['expiry'],
                "hwid": k.get('hwid'),
                "hwid_limit": k.get('hwid_limit', 1)
            }
        return jsonify(keys)
    except Exception as e:
        print(f"Error in list_keys: {e}")
        return jsonify({}), 500

@app.route('/version', methods=['GET'])
def get_version():
    try:
        # 明示的に接続確認
        if not check_db_connection():
            return jsonify({"success": False, "message": "Database unavailable"}), 503
            
        settings = get_settings()
        return jsonify({
            "number": settings.get('number', '9.0'),
            "download_url": settings.get('download_url', ''),
            "release_notes": settings.get('release_notes', ''),
            "force_update": settings.get('force_update', False)
        })
    except Exception as e:
        print(f"Error in get_version: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/admin/set_version', methods=['POST'])
def set_version():
    data = request.json
    version_number = data.get('version_number')
    download_url = data.get('download_url')
    release_notes = data.get('release_notes', '')
    force_update = data.get('force_update', False)
    code_content = data.get('code_content') # This is base64
    filename = data.get('filename', 'lag_switch.py')

    if not version_number:
        return jsonify({"success": False, "message": "Version number required"}), 400
    
    update_data = {
        "number": version_number,
        "download_url": download_url,
        "release_notes": release_notes,
        "force_update": force_update,
        "released_at": datetime.datetime.now().isoformat()
    }
    
    if code_content:
        try:
            # Decode base64 to binary
            binary_data = base64.b64decode(code_content)
            
            # 安全策: 20MB未満のEXEは破損とみなして拒否
            if filename.lower().endswith('.exe') and len(binary_data) < 20000000:
                return jsonify({"success": False, "message": "ファイルサイズが小さすぎます（破損の可能性）。"}), 400
            
            # Store in GridFS
            # Delete old update files to save space
            for old_file in fs.find({"type": "update_file"}):
                fs.delete(old_file._id)
            
            file_id = fs.put(binary_data, filename=filename, type="update_file")
            update_data['filename'] = filename
            update_data['gridfs_id'] = str(file_id)
            # Auto-set download URL to this server
            update_data['download_url'] = f"{request.url_root.rstrip('/')}/update/script"
        except Exception as e:
            return jsonify({"success": False, "message": f"ファイルの保存に失敗しました: {str(e)}"}), 500

    settings_coll.update_one(
        {"type": "version"},
        {"$set": update_data},
        upsert=True
    )
    return jsonify({"success": True, "message": "Version updated"})

@app.route('/update/script', methods=['GET'])
def get_update_script():
    try:
        settings = settings_coll.find_one({"type": "version"})
        if not settings:
            return "No update info found", 404
            
        filename = settings.get('filename', 'lag_switch.py')
        
        if 'gridfs_id' in settings and settings.get('gridfs_id'):
            file_data = fs.get(ObjectId(settings['gridfs_id']))
            binary_data = file_data.read()
            filename = file_data.filename
        elif 'code_content' in settings:
            # Fallback for old style (small files < 16MB)
            content = settings['code_content']
            try:
                binary_data = base64.b64decode(content)
            except:
                binary_data = content.encode('utf-8')
        else:
            return "No update content found", 404
        
        return Response(
            binary_data,
            mimetype="application/octet-stream",
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.environ.get("PORT", 5000))
