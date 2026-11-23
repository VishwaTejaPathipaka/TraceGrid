export function accountLinkToken(fragment) {
  if (!fragment.startsWith('#')) return null
  const tokens = new URLSearchParams(fragment.slice(1)).getAll('token')
  return tokens.length === 1 && /^[A-Za-z0-9_-]{43}$/.test(tokens[0]) ? tokens[0] : null
}
