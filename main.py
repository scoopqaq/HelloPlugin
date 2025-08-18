import asyncio
import httpx
import time
import logging
from pkg.plugin.context import register, handler, BasePlugin, EventContext
from pkg.plugin.events import PersonNormalMessageReceived

# --- 配置信息 ---
OPEN_KFID = "wk7m0ECAAAJIe_OYgcBEt5hGxXFrbqUA"
WECOM_CORP_ID = "ww490150746d039eda"
WECOM_SECRET = "iYNQBMi9vjFQsN6YM3opk1yCVdKfr_pGK_NVHkaBLJE"

# --- Access Token 缓存 ---
access_token_cache = {"token": None, "expires_at": 0}

async def get_access_token():
    now = int(time.time())
    if access_token_cache["token"] and access_token_cache["expires_at"] > now:
        return access_token_cache["token"]

    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_SECRET}"
    try:
        async with httpx.AsyncClient() as client:
            data = (await client.get(url)).json()
        if data.get("errcode") == 0:
            token = data["access_token"]
            access_token_cache.update(token=token, expires_at=now + 7000)
            return token
    except Exception as e:
        logging.exception("get_access_token error")
    return None

# --- 转人工后台任务 ---
async def real_transfer(logger, sender_id: str):
    logger.info("后台开始转人工流程")
    token = await get_access_token()
    if not token:
        logger.error("无法获取 access_token")
        return   # 这里也可以再给用户补一条失败消息

    # 取 external_userid
    idx = sender_id.find("wm")
    if idx == -1:
        logger.error("找不到 wm 前缀")
        return
    external_userid = sender_id[idx:].rstrip("!")

    # 调企微 API
    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}"
    payload = {"open_kfid": OPEN_KFID, "external_userid": external_userid, "service_state": 2}
    try:
        async with httpx.AsyncClient() as client:
            res = (await client.post(url, json=payload)).json()
        if res.get("errcode") == 0:
            logger.info("转人工成功")
        else:
            logger.error(f"转人工失败: {res}")
    except Exception:
        logger.exception("转人工异常")

# --- 插件主体 ---
@register(name="TransferToAgentFinal", description="处理转人工逻辑并调用企微API", version="1.0", author="YourName")
class TransferToAgentPlugin(BasePlugin):

    @handler(PersonNormalMessageReceived)
    async def handle_transfer_request(self, ctx: EventContext):
        msg = ctx.event.text_message
        if "转人工" in msg or "找客服" in msg:
            self.ap.logger.info("检测到转人工请求")
            # 1. 立即把提示发出去
            ctx.add_return("reply", ["正在为您转接人工服务，请稍候..."])
            # 2. 不再阻止默认行为，让框架把提示真正推送
            # 3. 后台异步完成真正转人工
            asyncio.create_task(
                real_transfer(self.ap.logger, ctx.event.sender_id)
            )
            # 4. 本 handler 正常结束，提示已发
