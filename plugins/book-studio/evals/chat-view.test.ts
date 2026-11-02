import { expect, test, mock } from 'claude-code/testing'

// BSC-CHAT-005: native host render seam; no model, files or network.
test('Book Studio progress is drawn in the conversation on terminal and desktop', async ($, on) => {
  on('tool.call', () => ({ result: { content: [], isError: false, structuredContent: {
    status: 'pass', view: { title: 'Synthetic book', stage: 'pilot_review_required',
      coverage: { translated: 4, eligible: 8, remaining: 4 } }
  } } }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['original host'] }))
  await $.tool.call({ tool: 'mcp__book_studio__view', project: 'synthetic' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'book-studio', component: 'AbovePrompt', surface,
      viewport: { columns: 100, rows: 30 }, props: {} })
    expect(await ui.find({ type: 'Text', text: /4 \/ 8/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /sample is ready/i })).toBeDefined()
    await ui.unmount()
  }
})

// BSC-CHAT-005: observation preserves the engine result; a refresh failure is visible.
test('refresh failure preserves completed tool output and marks the snapshot unavailable', async ($, on) => {
  const clock = mock.clock(on)
  const original = { content: [], isError: false, structuredContent: { status: 'pass', view: {
    title: 'Synthetic book', stage: 'full_active', coverage: { translated: 4, eligible: 8, remaining: 4 }
  } } }
  on('tool.call', () => ({ result: original }))
  on('mcp.call', () => ({ deny: 'synthetic disconnected server' }))
  on('session.start', () => ({ cwd: '/synthetic' }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['original host'] }))
  await $.session.start({ cwd: '/synthetic', surface: 'terminal', isInteractive: true })
  const response = await $.tool.call({ tool: 'mcp__book_studio__view', project: 'synthetic' })
  expect(response.result).toEqual(original)
  await clock.advance(6000)
  const ui = await $.ui.mount({ plugin: 'book-studio', component: 'AbovePrompt', surface: 'terminal',
    viewport: { columns: 100, rows: 30 }, props: {} })
  expect(await ui.find({ type: 'Text', text: /updates unavailable/ })).toBeDefined()
  await ui.unmount()
})

// BSC-CHAT-005: a completed earlier book must not suppress a new book's status.
test('switching from a finished book refreshes the newly selected project', async ($, on) => {
  const a = { title: 'Book A', stage: 'finished', coverage: { translated: 8, eligible: 8, remaining: 0 } }
  const b = { title: 'Book B', stage: 'pilot_active', coverage: { translated: 0, eligible: 8, remaining: 8 } }
  on('tool.call', ($, e) => ({ result: { content: [], isError: false,
    structuredContent: e.project === 'a' ? { status: 'pass', view: a } : { status: 'pass' } } }))
  on('mcp.call', () => ({ value: { content: [], isError: false, structuredContent: { status: 'pass', view: b } } }))
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['original host'] }))
  await $.tool.call({ tool: 'mcp__book_studio__view', project: 'a' })
  await $.tool.call({ tool: 'mcp__book_studio__status', project: 'b' })
  const ui = await $.ui.mount({ plugin: 'book-studio', component: 'AbovePrompt', surface: 'desktop',
    viewport: { columns: 100, rows: 30 }, props: {} })
  expect(await ui.find({ type: 'Text', text: /Book B.*0 \/ 8/ })).toBeDefined()
  await ui.unmount()
})

// BSC-CHAT-005: a late refresh cannot replace the active book with an old one.
test('a delayed refresh from an earlier project cannot overwrite the current project', async ($, on) => {
  let releaseA
  let markStarted
  const wait = new Promise(resolve => { releaseA = resolve })
  const started = new Promise(resolve => { markStarted = resolve })
  const a = { title: 'Book A', stage: 'full_active', coverage: { translated: 4, eligible: 8, remaining: 4 } }
  const b = { title: 'Book B', stage: 'pilot_active', coverage: { translated: 0, eligible: 8, remaining: 8 } }
  on('tool.call', ($, e) => ({ result: { content: [], isError: false,
    structuredContent: e.project === 'b' ? { status: 'pass', view: b } : { status: 'pass' } } }))
  on('mcp.call', async () => { markStarted(); await wait;
    return { value: { content: [], isError: false, structuredContent: { status: 'pass', view: a } } } })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['original host'] }))
  const first = $.tool.call({ tool: 'mcp__book_studio__status', project: 'a' })
  await started
  await $.tool.call({ tool: 'mcp__book_studio__view', project: 'b' })
  releaseA()
  await first
  const ui = await $.ui.mount({ plugin: 'book-studio', component: 'AbovePrompt', surface: 'desktop',
    viewport: { columns: 100, rows: 30 }, props: {} })
  expect(await ui.find({ type: 'Text', text: /Book B.*0 \/ 8/ })).toBeDefined()
  await ui.unmount()
})

// BSC-CHAT-005: older polls cannot rewind a newer same-project tool result.
test('a delayed poll cannot rewind newer progress for the same project', async ($, on) => {
  let releaseOld
  let markStarted
  let invocation = 0
  const wait = new Promise(resolve => { releaseOld = resolve })
  const started = new Promise(resolve => { markStarted = resolve })
  const view = { title: 'Book P', stage: 'pilot_review_required', coverage: { translated: 4, eligible: 8, remaining: 4 } }
  on('tool.call', () => ({ result: { content: [], isError: false,
    structuredContent: ++invocation === 1 ? { status: 'pass' } : { status: 'pass', view } } }))
  on('mcp.call', async () => { markStarted(); await wait; return { value: { content: [], isError: false,
    structuredContent: { status: 'pass', view: { ...view, coverage: { translated: 0, eligible: 8, remaining: 8 } } } } } })
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['original host'] }))
  const first = $.tool.call({ tool: 'mcp__book_studio__status', project: 'p' })
  await started
  await $.tool.call({ tool: 'mcp__book_studio__view', project: 'p' })
  releaseOld(); await first
  const ui = await $.ui.mount({ plugin: 'book-studio', component: 'AbovePrompt', surface: 'desktop',
    viewport: { columns: 100, rows: 30 }, props: {} })
  expect(await ui.find({ type: 'Text', text: /4 \/ 8/ })).toBeDefined()
  await ui.unmount()
})
