import httpx
import time
from datetime import datetime
import logging
from pkg.plugin.context import register, handler, BasePlugin, EventContext
from pkg.plugin.events import PersonNormalMessageReceived

# 【已更正！】使用你提供的正确导入路径
from pkg.platform.types import *

# --- 1. 配置信息 ---
# ====================================================================
OPEN_KFID = "wk1IEjWwAAzJpTMscnWXxttzvt8HQ1jw"
WECOM_CORP_ID = "ww9539a0a178d52277"
WECOM_SECRET = "ExcFX0jYD4J8flVmQ9cE9xsIec66P5qT79nnWez2Dx8"
# ====================================================================


# --- 2. Access Token 管理模块 ---
access_token_cache = { "token": None, "expires_at": 0 }

async def get_access_token():
    now = int(time.time())
    token, exp = access_token_cache["token"], access_token_cache["expires_at"]
    if token and exp > now:
        logging.info("Access Token: use cached.")
        return token

    logging.info("Access Token: Fetching new token...")
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CORP_ID}&corpsecret={WECOM_SECRET}"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        logging.info(f"gettoken response: {response.status_code} {response.text}")  # ← 新增
        data = response.json()

    if data.get("errcode") == 0:
        access_token_cache["token"] = data["access_token"]
        access_token_cache["expires_at"] = now + 7000
        return data["access_token"]
    else:
        logging.error(f"gettoken failed: {data}")
        return None


# --- 3. 插件主逻辑 ---
@register(name="TransferToAgentFinal", description="通过主动查询会话状态，实现精准的AI介入和转人工", version="3.0", author="YourName")
class TransferToAgentPlugin(BasePlugin):

    async def get_wecom_service_state(self, user_id: str):
        """调用API，主动查询指定用户的当前会话状态。"""
        token = await get_access_token()
        if not token:
            self.ap.logger.error("查询会话状态失败：无法获取 access_token。")
            return -1

        api_url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/get?access_token={token}"
        payload = {"open_kfid": OPEN_KFID, "external_userid": user_id}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url, json=payload)
                response.raise_for_status()
                result = response.json()
            
            if result.get("errcode") == 0:
                service_state = result.get("service_state")
                self.ap.logger.info(f"成功查询到用户 '{user_id}' 的会话状态为: {service_state}")
                return service_state
            else:
                self.ap.logger.error(f"查询用户 '{user_id}' 会话状态API返回错误: {result}")
                return -1
        except Exception as e:
            self.ap.logger.error(f"查询用户 '{user_id}' 会话状态时发生异常: {e}")
            return -1

    @handler(PersonNormalMessageReceived)
    async def handle_message(self, ctx: EventContext):
        try:
            original_user_id = ctx.event.sender_id
            wm_start_index = original_user_id.find("wm")
            if wm_start_index != -1:
                formatted_user_id = original_user_id[wm_start_index:]
                if formatted_user_id.endswith('!'):
                    formatted_user_id = formatted_user_id[:-1]
            else:
                self.ap.logger.warning(f"无法格式化用户ID: '{original_user_id}'。")
                return
        except AttributeError:
            self.ap.logger.error("无法从 ctx.event 获取 sender_id。")
            return

        current_service_state = await self.get_wecom_service_state(formatted_user_id)
        
        human_service_states = [2, 3]
        if current_service_state in human_service_states:
            self.ap.logger.info(f"用户 '{formatted_user_id}' 状态为 {current_service_state}，AI不介入。")
            ctx.prevent_default()
            return
        msg = ctx.event.text_message
        now = datetime.now()
        t = now.time()
        if "转人工" in msg or "找客服"in msg:
            if  time(0,0) <= t <=time(8,30):
                self.ap.logger.info(f"当前时间:{now.strftime('%Y-%m-%d %H:%M:%S')}，用户 '{formatted_user_id}' 请求转人工，执行转接...")
                try:
                    await ctx.reply(message_chain=MessageChain([Plain("人工客服在线时间为 每周一至周日 08:30-23:59，若有使用问题，您可以先留言，我们上线后会第一时间为您解答！")]))
                except Exception as e:
                    self.ap.logger.error(f"使用ctx.reply发送消息失败: {e}，请检查API用法。")
                await self.transfer_to_human(ctx,formatted_user_id)
            else:
                self.ap.logger.info(f"用户 '{formatted_user_id}' 请求转人工，执行转接...")
                try:
                    await ctx.reply(message_chain=MessageChain([Plain("正在为您转接人工客服，请稍候...")]))
                except Exception as e:
                    self.ap.logger.error(f"使用ctx.reply发送消息失败: {e}，请检查API用法。")
                await self.transfer_to_human(ctx, formatted_user_id)
        elif "[图片]" in msg or "[Image]" in msg:
            if time(0,0) <=t <=time(8,30):
                self.ap.logger.info(f"当前时间:{now.strftime('%Y-%m-%d %H:%M:%S')}，用户 '{formatted_user_id}' 请求转人工，执行转接...")
                try:
                    await ctx.reply(message_chain=MessageChain([Plain("智能客服暂不支持处理文字外的信息，且人工客服暂时未在线哦～人工客服在线时间为 每周一至周日 08:30-23:59，若有使用问题，您可以先留言，我们上线后会第一时间为您解答！")]))
                except Exception as e:
                    self.ap.logger.error(f"使用ctx.reply发送消息失败: {e}，请检查API用法。")
            else:
                self.ap.logger.info(f"用户'{formatted_user_id}'发送了图片，自动进行转人工,执行转接...") 
                try:
                    await ctx.reply(message_chain=MessageChain([Plain("智能客服无法处理文字以外的信息，已帮您转入人工服务，请稍等...")]))
                except Exception as e:
                    self.ap.logger.error(f"使用ctx.reply发送消息失败: {e}，请检查API用法。")
                await self.transfer_to_human(ctx, formatted_user_id)
    async def transfer_to_human(self, ctx: EventContext, user_id: str):

        token = await get_access_token()
        if not token:
            await ctx.reply(message_chain=MessageChain([Plain("抱歉，系统繁忙，转接失败了，请稍后重试。")]))
            ctx.prevent_default()
            return

        api_url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/service_state/trans?access_token={token}"
        payload = {"open_kfid": OPEN_KFID, "external_userid": user_id, "service_state": 2}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(api_url, json=payload)
                result = response.json()
            if result.get("errcode") == 0:
                self.ap.logger.info(f"成功将用户 '{user_id}' 转入待接入池。")
            else:
                self.ap.logger.error(f"转人工API失败: {result}")
                await ctx.reply(message_chain=MessageChain([Plain(f"抱歉，转接失败了({result.get('errmsg', '')})。")]))
        except Exception as e:
            self.ap.logger.error(f"转人工请求异常: {e}")
            await ctx.reply(message_chain=MessageChain([Plain("抱歉，转接时发生网络错误，请稍后重试。")]))
        finally:
            ctx.prevent_default()
