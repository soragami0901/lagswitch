from flask import Flask, request, jsonify
import json
import os
import datetime

app = Flask(__name__)
DB_FILE = 'licenses.json'

def load_db():
    if not os.path.exists(DB_FILE):
        return {}
    try:
        with open(DB_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"keys": {}, "global_payload": ""}

def save_db(data):
    # Ensure keys are in a sub-key if not already
    if "keys" not in data:
        data = {"keys": data, "global_payload": ""}
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

# 初期DB作成
if not os.path.exists(DB_FILE):
    save_db({"keys": {}, "global_payload": ""})

@app.route('/verify', methods=['POST'])
def verify_key():
    data = request.json
    key = data.get('key')
    hwid = data.get('hwid')
    
    db = load_db()
    keys = db.get("keys", {})
    
    if key not in keys:
        return jsonify({"valid": False, "message": "Invalid Key"}), 404
        
    key_data = keys[key]
    
    # 期限チェック
    if key_data['expiry'] != 'lifetime':
        try:
            exp_date = datetime.datetime.fromisoformat(key_data['expiry'])
            if datetime.datetime.now() > exp_date:
                return jsonify({"valid": False, "message": "Expired"}), 403
        except:
            pass # 日付形式エラーなどは一旦無視
            
    # HWIDチェック (初回は登録)
    if key_data['hwid'] is None:
        key_data['hwid'] = hwid
        save_db(db)
    elif key_data['hwid'] != hwid:
        return jsonify({"valid": False, "message": "HWID Mismatch"}), 403
        
    return jsonify({
        "valid": True, 
        "expiry": key_data['expiry'],
        "hwid": key_data['hwid'],
        "global_payload": db.get("global_payload", "")
    })

@app.route('/admin/add_key', methods=['POST'])
def add_key():
    # 本来は管理者認証が必要ですが、簡易版のため省略
    data = request.json
    key = data.get('key')
    expiry = data.get('expiry', 'lifetime')
    
    db = load_db()
    keys = db.get("keys", {})
    if key in keys:
        return jsonify({"success": False, "message": "Key exists"}), 400
        
    keys[key] = {
        "expiry": expiry,
        "hwid": None,
        "execute_payload": data.get('execute_payload', True)
    }
    save_db(db)
    return jsonify({"success": True, "message": "Key added"})

@app.route('/admin/delete_key', methods=['POST'])
def delete_key():
    data = request.json
    key = data.get('key')
    
    db = load_db()
    keys = db.get("keys", {})
    if key in keys:
        del keys[key]
        save_db(db)
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Key not found"}), 404

@app.route('/admin/toggle_payload', methods=['POST'])
def toggle_payload():
    data = request.json
    key = data.get('key')
    
    db = load_db()
    keys = db.get("keys", {})
    if key in keys:
        # トグル処理
        keys[key]['execute_payload'] = not keys[key].get('execute_payload', True)
        save_db(db)
        return jsonify({"success": True, "execute_payload": keys[key]['execute_payload']})
    return jsonify({"success": False}), 404

@app.route('/admin/reset_hwid', methods=['POST'])
def reset_hwid():
    data = request.json
    key = data.get('key')
    
    db = load_db()
    keys = db.get("keys", {})
    if key in keys:
        keys[key]['hwid'] = None
        save_db(db)
        return jsonify({"success": True})
    return jsonify({"success": False}), 404

@app.route('/admin/set_payload', methods=['POST'])
def set_payload():
    data = request.json
    payload = data.get('payload', '')
    
    db = load_db()
    db['global_payload'] = payload
    save_db(db)
    return jsonify({"success": True})

@app.route('/admin/get_payload', methods=['GET'])
def get_payload():
    db = load_db()
    return jsonify({"payload": db.get('global_payload', "")})

@app.route('/admin/list_keys', methods=['GET'])
def list_keys():
    db = load_db()
    return jsonify(db.get("keys", {}))

if __name__ == '__main__':
    # 外部公開する場合は host='0.0.0.0' にする
    app.run(host='0.0.0.0', port=5000)
