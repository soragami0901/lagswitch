from flask import Flask, request, jsonify
import json
import os
import datetime

app = Flask(__name__)
app = Flask(__name__)

# データ保存先の設定（環境変数 DATA_DIR があればそこを使う）
DATA_DIR = os.environ.get('DATA_DIR', os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(DATA_DIR, 'licenses.json')

# 起動時にDataディレクトリが存在するか確認
if not os.path.exists(DATA_DIR):
    try:
        os.makedirs(DATA_DIR)
    except:
        pass # 多分カレントディレクトリ等の場合は作れないかもしれないので無視

def load_db():
    default_db = {"keys": {}, "global_payload": ""}
    if not os.path.exists(DB_FILE):
        return default_db
    try:
        with open(DB_FILE, 'r') as f:
            data = json.load(f)
            # データ構造の修復/マイグレーション
            if "keys" not in data:
                # 古い形式の場合、ルートのキーをkeysに移動（versionなどを除く）
                keys = {}
                for k, v in data.items():
                    if k not in ["global_payload", "version", "keys"] and isinstance(v, dict) and "expiry" in v:
                        keys[k] = v
                data = {"keys": keys, "global_payload": data.get("global_payload", ""), "version": data.get("version")}
            return data
    except:
        return default_db

def save_db(data):
    # Ensure keys are in a sub-key if not already
    if "keys" not in data:
        data["keys"] = {}
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# 初期DB作成
if not os.path.exists(DB_FILE):
    save_db({
        "keys": {}, 
        "global_payload": "",
        "version": {
            "number": "5.3",
            "download_url": "",
            "release_notes": "Initial version",
            "force_update": False,
            "released_at": datetime.datetime.now().isoformat()
        }
    })

@app.route('/verify', methods=['POST'])
def verify_key():
    data = request.json
    key = data.get('key')
    hwid = data.get('hwid')
    
    db = load_db()
    
    if key not in db['keys']:
        return jsonify({"valid": False, "message": "Invalid Key"}), 404
        
    key_data = db['keys'][key]
    
    # 期限チェック
    if key_data['expiry'] != 'lifetime':
        try:
            exp_date = datetime.datetime.fromisoformat(key_data['expiry'])
            if datetime.datetime.now() > exp_date:
                return jsonify({"valid": False, "message": "Expired"}), 403
        except:
            pass # 日付形式エラーなどは一旦無視
            
    # HWIDチェック (初回は登録、または無制限の場合はチェックしない)
    hwid_limit = key_data.get('hwid_limit', 1)  # デフォルトは1台まで
    
    if hwid_limit == 'unlimited':
        # 無制限の場合はHWIDチェックをスキップ
        pass
    elif key_data['hwid'] is None:
        # 初回登録
        key_data['hwid'] = hwid
        save_db(db)
    elif key_data['hwid'] != hwid:
        return jsonify({"valid": False, "message": "HWID Mismatch"}), 403
        
    return jsonify({
        "valid": True, 
        "expiry": key_data['expiry'],
        "hwid": key_data.get('hwid', 'unlimited')
    })

@app.route('/admin/add_key', methods=['POST'])
def add_key():
    # 本来は管理者認証が必要ですが、簡易版のため省略
    data = request.json
    key = data.get('key')
    expiry = data.get('expiry', 'lifetime')
    
    db = load_db()
    if key in db['keys']:
        return jsonify({"success": False, "message": "Key exists"}), 400
    
    hwid_limit = data.get('hwid_limit', 1)  # デフォルトは1台まで
    
    db['keys'][key] = {
        "expiry": expiry,
        "hwid": None,
        "hwid_limit": hwid_limit
    }
    save_db(db)
    return jsonify({"success": True, "message": "Key added"})

@app.route('/admin/delete_key', methods=['POST'])
def delete_key():
    data = request.json
    key = data.get('key')
    
    db = load_db()
    if key in db['keys']:
        del db['keys'][key]
        save_db(db)
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Key not found"}), 404

@app.route('/admin/reset_hwid', methods=['POST'])
def reset_hwid():
    data = request.json
    key = data.get('key')
    
    db = load_db()
    if key in db['keys']:
        db['keys'][key]['hwid'] = None
        save_db(db)
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route('/admin/list_keys', methods=['GET'])
def list_keys():
    db = load_db()
    return jsonify(db['keys'])

@app.route('/version', methods=['GET'])
def get_version():
    """クライアントが最新バージョン情報を取得"""
    db = load_db()
    version_info = db.get('version', {
        "number": "5.3",
        "download_url": "",
        "release_notes": "",
        "force_update": False
    })
    return jsonify(version_info)

@app.route('/admin/set_version', methods=['POST'])
def set_version():
    """管理者が新しいバージョン情報を設定"""
    data = request.json
    version_number = data.get('version_number')
    download_url = data.get('download_url')
    release_notes = data.get('release_notes', '')
    force_update = data.get('force_update', False)
    
    if not version_number:
        return jsonify({"success": False, "message": "Version number required"}), 400
    
    db = load_db()
    db['version'] = {
        "number": version_number,
        "download_url": download_url,
        "release_notes": release_notes,
        "force_update": force_update,
        "released_at": datetime.datetime.now().isoformat()
    }
    save_db(db)
    return jsonify({"success": True, "message": "Version updated"})

if __name__ == '__main__':
    # 外部公開する場合は host='0.0.0.0' にする
    app.run(host='0.0.0.0', port=5000)
