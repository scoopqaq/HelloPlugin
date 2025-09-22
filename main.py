# ================= 新增工具函数 =================
import datetime as _dt
def is_pic_msg(ctx: EventContext) -> bool:
    """判断事件是否为图片消息（mirai 图片/企业微信图片统一用[图片]占位）"""
    text = ctx.event.text_message or ""
    return "[图片]" in text

def is_night() -> bool:
    """当前是否处于 00:00–08:30 的夜间时段"""
    now = _dt.datetime.now()
    night_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    night_end   = now.replace(hour=8, minute=30, second=0, microsecond=0)
    # 跨天区间
    if now >= night_start and now < night_end:
        return True
    return False

# ================= 改造后的 handle_message =================
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

    # ---- 1. 图片消息分支 ----
    if is_pic_msg(ctx):
        if is_night():
            await ctx.reply(message_chain=MessageChain([
                Plain("智能客服暂不支持处理文字外的信息，且人工客服暂时未在线哦～\n"
                      "人工客服在线时间为 每周一至周日 08:30-23:59，若有使用问题，您可以先留言，"
                      "我们上线后会第一时间为您解答！")
            ]))
        else:
            await ctx.reply(message_chain=MessageChain([
                Plain("智能客服无法处理文字以外的信息，已帮您转入人工服务，请稍等。")
            ]))
        # 无论夜间还是白天，都调 trans 接口生成待接入工单
        await self.transfer_to_human(ctx, formatted_user_id)
        return

    # ---- 2. 夜间“转人工”关键字分支 ----
    msg = ctx.event.text_message or ""
    if ("转人工" in msg or "找客服" in msg) and is_night():
        await ctx.reply(message_chain=MessageChain([
            Plain("人工客服在线时间为 每周一至周日 08:30-23:59，若有使用问题，您可以先留言，"
                  "我们上线后会第一时间为您解答！")
        ]))
        # 夜间也强制走 trans，让后台记录
        await self.transfer_to_human(ctx, formatted_user_id)
        return

    # ---- 3. 原有逻辑：先查状态再决定是否转人工 ----
    current_service_state = await self.get_wecom_service_state(formatted_user_id)
    human_service_states = [2, 3]
    if current_service_state in human_service_states:
        self.ap.logger.info(f"用户 '{formatted_user_id}' 状态为 {current_service_state}，AI不介入。")
        ctx.prevent_default()
        return

    # 白天正常关键字转人工
    if "转人工" in msg or "找客服" in msg:
        self.ap.logger.info(f"用户 '{formatted_user_id}' 请求转人工，执行转接...")
        await self.transfer_to_human(ctx, formatted_user_id)
