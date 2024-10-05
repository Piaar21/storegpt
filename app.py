# 클라우드 콘솔에 옮기는용
# 완성본
# 필요한 라이브러리 임포트
from flask import Flask, request, jsonify
import openai
import os
import requests
import time
import hashlib
import hmac
import json
import threading
import subprocess

# OpenAI 및 셀러툴 API 키 설정 (환경 변수에서 가져오기)
openai.api_key = os.environ.get('OPENAI_API_KEY')
SELLERTOOL_API_KEY = os.environ.get('SELLERTOOL_API_KEY')
SELLERTOOL_SECRET_KEY = os.environ.get('SELLERTOOL_SECRET_KEY')

# Flask 앱 생성
app = Flask(__name__)

# 시그니처 생성 함수
def generate_signature(api_key, secret_key, timestamp):
    if not api_key or not secret_key:
        raise ValueError("API 키 또는 시크릿 키가 설정되지 않았습니다.")
    message = api_key + timestamp
    return hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()

# 첫 번째 API 호출: product-options
def get_product_options(product_name):
    REQUEST_URL_OPTIONS = 'https://sellertool-api-server-function.azurewebsites.net/api/product-options'
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(SELLERTOOL_API_KEY, SELLERTOOL_SECRET_KEY, timestamp)
    headers = {
        'x-sellertool-apiKey': SELLERTOOL_API_KEY,
        'x-sellertool-timestamp': timestamp,
        'x-sellertool-signiture': signature
    }
    params = {
        'productName': product_name
    }
    try:
        response = requests.get(REQUEST_URL_OPTIONS, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            if 'content' in data and isinstance(data['content'], list):
                return data['content']
            else:
                print("첫 번째 API 응답 형식이 예상과 다릅니다.")
                return None
        else:
            print(f"첫 번째 API 호출 에러: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        print(f"첫 번째 API 요청 중 오류 발생: {e}")
        return None

# 두 번째 API 호출: inventories/search/stocks-by-optionCodes
def get_stock_by_option_codes(option_codes):
    REQUEST_URL_STOCKS = 'https://sellertool-api-server-function.azurewebsites.net/api/inventories/search/stocks-by-optionCodes'
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(SELLERTOOL_API_KEY, SELLERTOOL_SECRET_KEY, timestamp)
    headers = {
        'x-sellertool-apiKey': SELLERTOOL_API_KEY,
        'x-sellertool-timestamp': timestamp,
        'x-sellertool-signiture': signature
    }
    body = {
        "optionCodes": option_codes
    }
    try:
        response = requests.post(REQUEST_URL_STOCKS, json=body, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if 'content' in data and isinstance(data['content'], list):
                return data['content']
            else:
                print("두 번째 API 응답 형식이 예상과 다릅니다.")
                return None
        else:
            print(f"두 번째 API 호출 에러: {response.status_code}, {response.text}")
            return None
    except Exception as e:
        print(f"두 번째 API 요청 중 오류 발생: {e}")
        return None

# 데이터 조인 함수
def join_data(product_options, stock_data):
    joined_data = []
    options_dict = {item['productOptionCode'].strip().upper(): item for item in product_options}

    for stock_item in stock_data:
        option_code = stock_item.get('code', '').strip().upper()
        if option_code and option_code in options_dict:
            joined_item = options_dict[option_code].copy()
            joined_item.update({
                '재고 수량': stock_item.get('stockUnit', 0),
                '입고 수량': stock_item.get('receiveUnit', 0),
                '출고 수량': stock_item.get('releaseUnit', 0)
            })
            joined_data.append(joined_item)
    return joined_data

# GPT 응답 생성 함수
def generate_gpt_response(prompt, joined_data=None):
    try:
        if joined_data:
            data_str = json.dumps(joined_data, ensure_ascii=False, indent=2)
            full_prompt = f"""다음은 제품의 옵션 및 재고 정보입니다:
{data_str}

사용자의 질문에 답변해 주세요.

사용자 질문: {prompt}
"""
        else:
            full_prompt = prompt

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # 또는 "gpt-4"
            messages=[
                {"role": "system", "content": "당신은 사용자의 질문에 친절하게 답변해주는 어시스턴트입니다."},
                {"role": "user", "content": full_prompt}
            ],
            max_tokens=500,
            temperature=0.7,
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"OpenAI API 오류: {e}")
        return "죄송하지만 현재 요청을 처리할 수 없습니다."

# 웹훅 엔드포인트 설정
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        user_message = data['userRequest']['utterance']

        # '/재고 상품명' 명령어 처리
        if user_message.startswith('/재고'):
            product_name = user_message[len('/재고'):].strip()
            if product_name:
                product_options = get_product_options(product_name)
                if product_options:
                    option_codes = [item['productOptionCode'].strip().upper() for item in product_options if 'productOptionCode' in item]
                    if not option_codes:
                        response_text = "옵션 코드를 찾을 수 없습니다."
                    else:
                        stock_data = get_stock_by_option_codes(option_codes)
                        if stock_data:
                            joined_data = join_data(product_options, stock_data)
                            if joined_data:
                                # 옵션 리스트와 재고 개수 출력
                                options_list = [f"옵션: {item['productOptionName']}, 재고 수량: {item['재고 수량']}" for item in joined_data]
                                response_text = "\n".join(options_list)
                            else:
                                response_text = "데이터를 조합할 수 없습니다."
                        else:
                            response_text = "재고 데이터를 가져올 수 없습니다."
                else:
                    response_text = f"'{product_name}' 제품의 옵션 정보를 가져올 수 없습니다."
            else:
                response_text = "제품 이름을 입력해 주세요."
        else:
            # 일반 질문 처리
            response_text = generate_gpt_response(user_message)

        # 카카오톡으로 보낼 응답 형식 설정
        kakao_response = {
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": response_text
                        }
                    }
                ]
            }
        }
        return jsonify(kakao_response)
    except Exception as e:
        print(f"웹훅 처리 중 오류 발생: {e}")
        return jsonify({'error': '서버 오류가 발생했습니다.'}), 500

# LocalTunnel 실행 및 URL 가져오기
tunnel_url = ''

def run_lt():
    global tunnel_url
    p = subprocess.Popen(['lt', '--port', '5000'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    for line in iter(p.stdout.readline, ''):
        if 'your url is:' in line:
            tunnel_url = line.strip().split(' ')[-1]
            print(f"LocalTunnel URL: {tunnel_url}")
            break

t = threading.Thread(target=run_lt)
t.start()

# LocalTunnel이 실행될 때까지 대기
time.sleep(5)

# Flask 앱 실행
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
