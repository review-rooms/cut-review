import { expect, test } from 'claude-code/testing'

const BAND = {
  plugin: 'cut-review',
  component: 'AbovePrompt',
  props: { hasSurvey: false, isWorking: false, maxRows: 6, bodyColumns: 100, scroll: { offset: 0, bodyRows: 6 }, view: {} },
} as const

const ROOM = {
  title: 'Launch cuts',
  cuts: [{ key: 'teaser', file: 'teaser.mp4' }, { key: 'film', title: 'Launch film' }],
  sets: [{ key: 'film-board', storyboardFor: 'film' }, { key: 'carousel', dir: 'carousel' }],
}
const NOTES = [
  { id: 'a', status: 'open', thread: [{ by: 'u1', text: 'also this' }] },   // open and waiting: one to apply, not two
  { id: 'b', status: 'fixed', thread: [{ by: 'u1', text: 'why?' }] },
  { id: 'c', status: 'resolved' },
]

// stands for the engine: the project's files, the session, prompts, and the empty band beneath the plugin
function files(on: any, have: Record<string, unknown>, sent: string[] = []) {
  // a relative path reaches the engine resolved against the working directory
  const at = (path: string) => Object.keys(have).find(k => path === k || path.endsWith('/' + k))
  on('fs.read', (_: unknown, e: { path: string }) => { const k = at(e.path); return k ? { value: JSON.stringify(have[k]) } : { deny: 'no such file' } })
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('command.run', (_: unknown, e: { command: string; args: string }) => { sent.push(`/${e.command} ${e.args}`); return { text: '' } })
  on('ui.render', ($: any, e: any) => { const { Box } = $.ui.resolve(e); return <Box /> })
}

test('in a room project: where the room stands, and one press per step', async ($, on) => {
  const sent: string[] = []
  files(on, { 'room.json': ROOM, '.cut-review/state.json': { artifact: 'https://claude.ai/artifact/x' }, '.cut-review/notes.json': NOTES }, sent)
  await $.session.start({ cwd: '/room', surface: 'desktop', isInteractive: true })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...BAND, surface })
    expect((await ui.find({ type: 'Text', text: /storyboard/ }))?.text).toBe('1 storyboard · 1 cut · 1 set · 1 open · 1 to check · 2 replies to answer')
    expect((await ui.find({ type: 'Button', key: 'apply' }))?.text).toBe('Apply 2 notes')
    await ui.press({ key: 'apply' })
    await ui.press({ key: 'make' })
    await ui.unmount()
  }
  expect(sent.length).toBe(4)   // both surfaces, both presses
  expect(sent[2]).toBe(sent[0])
  expect(sent[0]).toMatch(/^\/cut-review:review-room apply my notes/)
  expect(sent[1]).toMatch(/make the "Launch film" video from its storyboard/)
})

test('no room here: no band', async ($, on) => {
  files(on, {})
  await $.session.start({ cwd: '/elsewhere', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect(await ui.find({ type: 'Button' })).toBe(undefined)
  await ui.unmount()
})

test('nothing to apply: Check notes; Hide hides it', async ($, on) => {
  files(on, { 'room.json': { title: 'R', cuts: [{ key: 'a', file: 'a.mp4' }] } })
  await $.session.start({ cwd: '/room', surface: 'desktop', isInteractive: true })
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' })
  expect((await ui.find({ type: 'Button', key: 'check' }))?.text).toBe('Check notes')
  expect(await ui.find({ type: 'Button', key: 'apply' })).toBe(undefined)
  await ui.press({ key: 'hide' })
  expect(await ui.find({ type: 'Button' })).toBe(undefined)
  await ui.unmount()
})
