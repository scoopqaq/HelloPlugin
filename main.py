# -*- coding: utf-8 -*-
# plugins/transfer_img.py
import datetime as _dt
import httpx
import time
import logging

from pkg.plugin.context import register, handler, BasePlugin, EventContext
from pkg.plugin.events import PersonNormalMessageReceived
from pkg.platform.types import MessageChain, Plain

# ========== 1. 企业微信配置（改成你自己的） ==========
OPEN_KFID      = "wk7m0ECAAAJIe_OYgcBEt5hGxXFrbqUA"
WECOM_CORP_ID  = "ww490150746d039eda"
WECOM_SECRET   = "iYNQBMi9vjFQsN6YM3opk1yCVdKfr_pGK_NVHkaBLJE"
# =====================================================

# ---------- 2. AccessToken 管理（直接复用老代码） ----------
_access_token_cache = {"token": None, "expires_at": 0}

async def get_access_token() -> str | None:
    now = int(time.time())
    if _access_token_cache["token"] and _access_token_cache["expires_at"] > now:
        return _access_token_cache["token"]

    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_SECRET}"
    try:
        async with httpx.AsyncClient() as cli:
            r = await cli.get(url)
            r.raise_for_status()
            data = r.json()
        if data.get("errcode") == 0:
            _access_token_cache["token"]      = data["access_token"]
            _access_token_cache["expires_at"] = now + 7000
            return _access_token_cache["token"]
        else:
            logging.error(f"gettoken failed: {data}")
    except Exception as e:
        logging.error(f"gettoken exception: {e}")
    return None
# -------------------------------------------------------------

# -------------- 3. 两个小工具 --------------
def is_night() -> bool:
    """00:00–08:30 返回 True"""
    now = _dt.datetime.now().time()
    return now < _dt.time(8, 30)

def format_uid(raw: str) -> str | None:
    """把 sender_id 提取成 wmxxx 格式"""
    idx = raw.find("wm")
    if idx == -1:
        return None
    return raw[idx:].rstrip("!")
# ------------------------------------------

# -------------- 4. 真正转人工 --------------
async def transfer_to_human(ctx: EventContext, user_id: str) -> None:
    token = await get_access_token()
    if not token:
        await ctx.reply(MessageChain([Plain("系统繁忙，转接失败，请稍后再试")]))
        ctx.prevent_default()
        return

    url     = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}"
    payload = {"open_kfid": OPEN_KFID, "external_userid": user_id, "service_state": 2}
    try:
        async with httpx.AsyncClient() as cli:
            r = await cli.post(url, json=payload)
            r.raise_for_status()
            if r.json().get("errcode") == 0:
                logging.info(f"转人工成功：{user_id}")
            else:
                logging.error(f"转人工失败：{r.json()}")
                await ctx.reply(MessageChain([Plain("转接失败，请稍后重试")]))
    except Exception as e:
        logging.error(f"转人工异常：{e}")
        await ctx.reply(MessageChain([Plain("网络异常，请稍后重试")]))
    finally:
        ctx.prevent_default()

# ================= 5. 插件主体 =================
@register(
    name="TransferImg",
    description="图片消息立即转人工，夜间时段特殊提示",
    version="1.0",
    author="RockChinQ"
)
class TransferImgPlugin(BasePlugin):
    """插件加载与卸载不做额外动作"""
    def __init__(self, host): super().__init__(host)
    async def initialize(self): pass
    def __del__(self): pass

    # 主入口
    @handler(PersonNormalMessageReceived)
    async def handle(self, ctx: EventContext):
        msg = ctx.event.text_message or ""
        uid = format_uid(ctx.event.sender_id)
        if not uid:                     # 格式不对直接放过
            return

        # ---- 1. 图片消息 ----
        if msg == "[图片]":
            if is_night():
                text = ("智能客服暂不支持处理文字外的信息，且人工客服暂时未在线哦～\n"
                        "人工客服在线时间为 每周一至周日 08:30-23:59，若有使用问题，"
                        "您可以先留言，我们上线后会第一时间为您解答！")
            else:
                text = "智能客服无法处理文字以外的信息，已帮您转入人工服务，请稍等。"
            await ctx.reply(MessageChain([Plain(text)]))
            await transfer_to_human(ctx, uid)
            return

        # ---- 2. 夜间关键字“转人工/找客服” ----
        if ("转人工" in msg or "找客服" in msg) and is_night():
            text = ("人工客服在线时间为 每周一至周日 08:30-23:59，若有使用问题，"
                    "您可以先留言，我们上线后会第一时间为您解答！")
            await ctx.reply(MessageChain([Plain(text)]))
            await transfer_to_human(ctx, uid)
            return

        # ---- 3. 其它消息走默认流程 ----
        if ("转人工" in msg or "找客服" in msg):
            text = ("正在为您转接人工客服，请稍候...")
            await ctx.reply(MessageChain([Plain(text)]))
            await transfer_to_human(ctx, uid)
            return
        #test