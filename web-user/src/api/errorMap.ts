/** 已知错误码的中文 fallback；后端通常自带 message，这里只在 message 缺失时兜底。 */
export const ERROR_MESSAGES: Record<string, string> = {
  INSUFFICIENT_BALANCE: '余额不足，请先充值',
  SESSION_LIMIT: '同时进行的会话数已达上限',
  SESSION_NOT_FOUND: '会话不存在或已结束',
  FORBIDDEN: '没有权限',
  RECHARGE_NOT_CONFIGURED: '平台收款未配置，请联系管理员',
  AMOUNT_TOO_SMALL: '金额低于最低充值额',
  AMOUNT_INSUFFICIENT: '链上转账金额不足',
  INVALID_AMOUNT: '金额格式错误',
  INVALID_FROM_ADDRESS: '转出地址格式错误',
  INVALID_TX_HASH: '交易 hash 格式错误（应为 64 位 hex）',
  ORDER_NOT_PENDING: '订单状态已变更，无法继续操作',
  ORDER_EXPIRED: '订单已过期，请重新创建',
  ORDER_NOT_FOUND: '订单不存在',
  HASH_ALREADY_USED: '该交易 hash 已被使用',
  TX_NOT_FOUND: '链上未找到该交易（可能尚未确认）',
  TX_NOT_SUCCESS: '交易未成功执行',
  WRONG_CONTRACT: '不是 USDT-TRC20 合约转账',
  WRONG_METHOD: '不是 transfer 调用',
  WRONG_TO: '收款地址不匹配',
  WRONG_FROM: '转出地址与订单声明不一致',
  NOT_ENOUGH_CONFIRMATIONS: '链上确认数不足，请稍后再提交',
  TX_AFTER_EXPIRY: '交易时间晚于订单有效期',
  TRON_RPC_ERROR: '链上节点暂时不可用，请稍后重试',
  TRON_RPC_BAD_REQUEST: '链上请求被拒绝，请联系管理员',
  RECHARGE_INTERNAL_ERROR: '充值入账失败，请联系管理员',
  USERNAME_TAKEN: '该用户名已被注册',
  WEAK_PASSWORD: '密码至少 8 位，且需要包含字母和数字',
  INVALID_CREDENTIALS: '用户名或密码错误',
}

export function describeError(code: string, fallback?: string): string {
  return ERROR_MESSAGES[code] ?? fallback ?? '操作失败，请稍后重试'
}
