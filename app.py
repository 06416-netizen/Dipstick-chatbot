import os
import cv2
import numpy as np
import tempfile
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, ImageMessage, TextMessage,
    TextSendMessage, FlexSendMessage
)
from skimage.color import deltaE_ciede2000, rgb2lab
from pillow_heif import register_heif_opener

# รองรับรูป HEIC จาก iPhone
register_heif_opener()

# =========================
# 1) CONFIG (ใช้ Environment Variable)
# =========================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
app = Flask(__name__)

user_history = {}
last_analysis = {}

# =========================
# 2) TEMPLATE สี (LAB)
# =========================
GLUCOSE_TEMPLATES = {
    "Negative": [82, -18, 12],
    "Trace (5 mmol/l)": [78, -22, 18],
    "1+ (15)": [62, -10, 45],
    "2+ (30)": [54, -2, 52],
    "3+ (60)": [44, 6, 42],
    "4+ (110)": [32, 12, 28]
}

# =========================
# 3) วิเคราะห์ ROI
# =========================
def get_precise_glucose_roi(img):
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]

    cnts, _ = cv2.findContours(
        thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not cnts:
        return None

    c = max(cnts, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(c)
    strip = img[y:y+h, x:x+w]

    if strip.shape[1] > strip.shape[0]:
        strip = cv2.rotate(strip, cv2.ROTATE_90_CLOCKWISE)

    strip = cv2.resize(strip, (120, 1400))
    roi = strip[910:1000, 25:95]

    return roi

def analyze_glucose_level(roi):
    avg_bgr = np.median(roi, axis=(0, 1))
    avg_lab = rgb2lab(
        np.uint8([[avg_bgr[::-1]]]) / 255.0
    ).flatten()

    best, min_diff = "Unknown", 999
    for level, lab in GLUCOSE_TEMPLATES.items():
        diff = deltaE_ciede2000(avg_lab, np.array(lab))
        if diff < min_diff:
            min_diff = diff
            best = level
    return best

# =========================
# 4) Flex Message
# =========================
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

# =========================
# 5) Webhook
# =========================
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
            TextSendMessage(text="❌ วิเคราะห์ภาพไม่ได้ กรุณาถ่ายให้แผ่นตรวจชัดและตรง")
        )
        return

    result = analyze_glucose_level(roi)
    last_analysis[uid] = result

    now = datetime.now().strftime("%d/%m %H:%M")
    user_history.setdefault(uid, []).append(f"{now} | {result}")

    line_bot_api.reply_message(
        event.reply_token,
        create_flex_report(result)
    )

# =========================
# 6) RUN (สำหรับ Render)
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
