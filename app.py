import os
import cv2
import tempfile
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, ImageMessage, TextMessage,
    TextSendMessage, FlexSendMessage
)

from ai import get_precise_glucose_roi, analyze_glucose_level

app = Flask(__name__)

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

user_history = {}
last_analysis = {}

def create_flex_report(result):
    if result == "Negative":
        color = "#06C755"
    elif result in ["Trace (5 mmol/l)", "1+ (15)"]:
        color = "#F1C40F"
    else:
        color = "#EF4444"

    return FlexSendMessage(
        alt_text="Urine Glucose Result",
        contents={
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "Urine Glucose", "weight": "bold", "size": "xl"},
                    {"type": "text", "text": result, "color": color, "size": "xxl", "weight": "bold"}
                ]
            }
        }
    )

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    uid = event.source.user_id
    content = line_bot_api.get_message_content(event.message.id)

    with tempfile.NamedTemporaryFile(delete=False) as f:
        for chunk in content.iter_content():
            f.write(chunk)
        path = f.name

    img = cv2.imread(path)
    os.remove(path)

    roi = get_precise_glucose_roi(img)
    if roi is None:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ วิเคราะห์ภาพไม่สำเร็จ กรุณาถ่ายให้ชัดและพื้นหลังเข้ม")
        )
        return

    result = analyze_glucose_level(roi)
    last_analysis[uid] = result

    user_history.setdefault(uid, []).append(result)

    line_bot_api.reply_message(
        event.reply_token,
        create_flex_report(result)
    )
