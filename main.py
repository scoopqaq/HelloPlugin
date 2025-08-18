# -*- coding: utf-8 -*-

import httpx
import time
import logging
from pkg.plugin.context import register, handler, BasePlugin, EventContext
from pkg.plugin.events import PersonNormalMessageReceived

# --- 1. 配置信息 ---
# 请将这里的配置项替换为你自己的企业微信后台信息
# ====================================================================
OPEN_KFID = "wk7m0ECAAAJIe_OYgcBEt5hGxXFrbqUA"  # 你的企业微信客服账号ID
WECOM_CORP_ID = "ww490150746d039eda" # 你的企业ID
WECOM_SECRET = "iYNQBMi9vjFQsN6YM3opk1yCVdKfr_pGK_NVHkaBLJE" # 你的客服应用Secret
# ====================================================================


# --- 2. 核心：会话状态管理器 ---
# 这个字典就是我们的“小本子”，用来记录哪个用户正在由人工服务。
# key 是用户的 external_userid, value 是状态标识（例如 "human"）。
# 注意：这是一个内存级的缓存。如果你的机器人服务重启，所有状态都会丢失。
# 对于生产环境，如果需要持久化，可以考虑替换为 Redis 或数据库。
user_service_state = {}


# --- 3. Access Token 管理模块 ---
# 全局缓存企业微信的 access_token，有效期为2小时，我们提前刷新。
access_token_cache = {
    "token": None,
    "expires_at": 0
}

async def get_access_token():
    """
    异步获取并缓存企业微信的 access_token。
    如果缓存中的 token 有效，则直接返回；否则，重新请求并缓存。
    """
    now = int(time.time())
    # 如果缓存存在且未过期（我们设置了7000秒的安全期，比官方7200秒短）
    if access_token_cache["token"] and access_token_cache["expires_at"] > now:
        logging.info("Access Token: Using cached token.")
        return access_token_cache["token"]

    # 缓存无效或已过期，需要重新获取
    logging.info("Access Token: Fetching new token...")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_SECRET}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()  # 如果HTTP状态码不是2xx，则抛出异常
            data = response.json()

        if data.get("errcode") == 0:
            token = data["access_token"]
            # 更新缓存
            access_token_cache["token"] = token
            access_token_cache["expires_at"] = now + 7000
            logging.info("Access Token: Successfully fetched and cached new token.")
            return token
        else:
            logging.error(f"Access Token: Failed to get token from API. Response: {data}")
            return None
    except Exception as e:
        logging.error(f"Access Token: An exception occurred while requesting token. Exception: {e}")
        return None


# --- 4. 插件主逻辑 ---
@register(name="TransferToAgentFinal", description="处理转人工逻辑，并通过状态管理节省AI资源", version="1.1", author="YourName")
class TransferToAgentPlugin(BasePlugin):

    @handler(PersonNormalMessageReceived)
    async def handle_message(self, ctx: EventContext):
        """
        处理所有个人消息，实现智能转人工及状态拦截。
        """
        # --- 步骤 1: 获取并格式化用户ID ---
        # 无论如何，我们都需要先拿到一个干净的用户ID用于后续操作。
        try:
            original_user_id = ctx.event.sender_id
            # 根据经验，ID通常以 "wm" 开头，我们以此为标准进行截取
            wm_start_index = original_user_id.find("wm")
            if wm_start_index != -1:
                formatted_user_id = original_user_id[wm_start_index:]
                # 移除末尾可能存在的 "!" 符号
                if formatted_user_id.endswith('!'):
                    formatted_user_id = formatted_user_id[:-1]
            else:
                self.ap.logger.warning(f"无法格式化用户ID: '{original_user_id}'。插件将忽略此消息。")
                return # ID格式不正确，直接退出，不进行任何处理
        except AttributeError:
            self.ap.logger.error("无法从 ctx.event 中获取 sender_id 属性。")
            return

        # --- 步骤 2: 状态检查（节省资源的核心）---
        # 这是整个逻辑的第一道防线。
        if user_service_state.get(formatted_user_id) == "human":
            self.ap.logger.info(f"用户 '{formatted_user_id}' 处于人工服务状态，已拦截消息，防止AI处理造成资源浪费。")
            ctx.prevent_default()  # 阻止消息流向其他插件（如AI回复插件）
            return                 # 函数提前结束

        # --- 步骤 3: 意图判断 ---
        # 只有当用户不在人工服务状态时，才会执行到这里。
        # 我们检查消息是否包含转人工的关键词。
        msg = ctx.event.text_message
        if "转人工" in msg or "找客服" in msg:
            self.ap.logger.info(f"用户 '{formatted_user_id}' 请求转接人工服务，开始执行转接流程。")
            
            # --- 步骤 4: 执行转人工操作 ---
            await self.transfer_to_human(ctx, formatted_user_id)
    
    async def transfer_to_human(self, ctx: EventContext, user_id: str):
        """
        调用企业微信API，将用户会话转接给人工，并更新内部状态。
        """
        # a. 友好提示用户
        ctx.add_return("reply", ["正在为您转接人工客服，请稍候..."])
        
        # b. 获取access_token
        token = await get_access_token()
        if not token:
            self.ap.logger.error("转人工失败：无法获取 access_token。")
            ctx.add_return("reply", ["抱歉，系统繁忙，转接失败，请稍后再试。"])
            ctx.prevent_default()
            return

        # c. 调用企微API
        api_url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}"
        payload = {
            "open_kfid": OPEN_KFID,
            "external_userid": user_id,
            "service_state": 2  # 2: 代表转由人工接待
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                result = response.json()

            # d. 处理API结果并更新状态
            if result.get("errcode") == 0:
                self.ap.logger.info(f"成功将用户 '{user_id}' 转接至人工！现在更新其状态。")
                # !!! 核心操作：在“小本子”上记下这个用户的状态 !!!
                user_service_state[user_id] = "human"
            else:
                self.ap.logger.error(f"调用企微转人工API失败: {result}")
                error_msg = result.get('errmsg', '未知错误')
                ctx.add_return("reply", [f"抱歉，转接失败了({error_msg})，您可以稍后重试。"])

        except Exception as e:
            self.ap.logger.error(f"请求企微转人工API时发生异常: {e}")
            ctx.add_return("reply", ["抱歉，转接过程中发生网络错误，请稍后再试。"])
        
        finally:
            # e. 最终拦截
            # 无论转接成功还是失败，对于“转人工”这条指令消息本身，
            # 我们都不希望AI再对它进行回复。
            ctx.prevent_default()
