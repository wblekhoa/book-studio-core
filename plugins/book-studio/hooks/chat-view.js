// Read-only presentation adapter. All approvals and corrections remain chat instructions.
let current = null
let active = null
let refreshing = null
let unavailable = false
let revision = 0

function snapshot(result) {
  const payload = result?.structuredContent
  return !result?.isError && payload?.status === 'pass' && payload.view?.coverage ? payload.view : null
}

async function refresh($) {
  if (!active || refreshing === active || current?.stage === 'finished') return
  const selection = active
  const version = revision
  refreshing = selection
  try {
    const result = await $.mcp.call(selection.server, 'view', { project: selection.project })
    if (active !== selection || revision !== version) return
    const view = snapshot(result)
    if (view) { current = view; unavailable = false } else unavailable = true
  } catch { if (active === selection && revision === version) unavailable = true }
  finally { if (refreshing === selection) refreshing = null; $.ui.invalidate('ui.render') }
}

export function register(on) {
  on('session.start', async ($, e, next) => {
    $.clock.every(6000, async () => { await refresh($) })
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    if (!/^mcp__.*book[_-]studio.*__(view|review|status|start|pilot|apply_response|apply_drafts|finish|verify)$/.test(e.tool) || typeof e.project !== 'string') return next(e)
    const server = e.tool.slice(5, e.tool.lastIndexOf('__'))
    if (!active || active.server !== server || active.project !== e.project) {
      active = { server, project: e.project }; current = null; unavailable = false
      $.ui.invalidate('ui.render')
    }
    const selection = active
    const version = ++revision
    const result = await next(e)
    if (active !== selection || revision !== version) return result
    const view = snapshot(result?.result)
    if (view) { current = view; unavailable = false; $.ui.invalidate('ui.render') }
    else await refresh($)
    return result
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const original = await next(e)
    if (!current) return original
    const { Box, Text } = $.ui.resolve(e)
    const c = current.coverage
    const stage = { pilot_proposed: 'Sample proposed', pilot_active: 'Translating the sample',
      pilot_review_required: 'Your sample is ready', full_active: 'Translating the book',
      finished: 'Your book is ready' }[current.stage] || 'Book in progress'
    return Box({ flexDirection: 'column', children: [original,
      Text({ children: [`Book Studio · ${current.title || current.project} · ${c.translated} / ${c.eligible} passages`], dimColor: true }),
      Text({ children: [unavailable ? 'Progress updates unavailable. Ask the AI to check the project.' : `${stage} · continue in chat`] })
    ] })
  })
}
