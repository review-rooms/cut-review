// The band above the prompt in a project that has a review room (room.json): where the room stands, and one press
// for each step of the review loop. Every button only asks Claude, through the skill; the review-room skill does the work.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { RoomInfo } from '../types'

const room = atom({ plugin: 'cut-review', key: 'room' } as const, null)
const hidden = atom({ plugin: 'cut-review', key: 'hidden' } as const, false)

// each button runs the review-room skill with what to do, as if the person typed `/cut-review:review-room …`
const SKILL = 'cut-review:review-room'
const ASK = {
  apply: 'apply my notes: export the notes and replies, fix what they ask, re-render, swap the new versions in and answer each one.',
  check: 'check my review room for new notes, replies and verdicts.',
  plan: 'plan a new video for the room: ask me whether it gets a storyboard first or goes straight to video, then make it.',
  update: 'update the room: rebuild it, upload and write what changed, and republish the page if it is older.',
  make: (cut: string) => `make the "${cut.replace(/\s+/g, ' ').slice(0, 80)}" video from its storyboard: first check the storyboard's notes and verdict in the room.`,
}

type Manifest = { title?: string; cuts?: { key: string; file?: string; title?: string }[]; sets?: { key: string; storyboardFor?: string; platform?: string }[] }
type Note = { status?: string; thread?: { by?: string }[] }

const json = async ($: EngineInterface, path: string): Promise<unknown> => {
  try { return JSON.parse(await $.fs.read(path)) } catch { return null }
}
// the owner wrote last in the note's thread: Claude owes an answer
const waiting = (n: Note) => { const t = n?.thread; return Array.isArray(t) && t.length > 0 && t[t.length - 1]?.by !== 'claude' }
const list = <T,>(x: unknown): T[] => (Array.isArray(x) ? x : [])

// shortcut: reads the last export (.cut-review/notes.json), not the live room; `Check notes` refreshes it
async function load($: EngineInterface): Promise<RoomInfo | null> {
  const [raw, rawState, rawNotes] = await Promise.all(['room.json', '.cut-review/state.json', '.cut-review/notes.json'].map(f => json($, f)))
  if (!raw || typeof raw !== 'object') return null
  const m = raw as Manifest, artifact = (rawState as { artifact?: unknown } | null)?.artifact
  const cuts = list<NonNullable<Manifest['cuts']>[number]>(m.cuts), sets = list<NonNullable<Manifest['sets']>[number]>(m.sets)
  const notes = list<Note>(rawNotes)
  const boards = sets.filter(s => s?.storyboardFor)
  const title = (key: string) => cuts.find(c => c?.key === key)?.title ?? key
  return {
    title: String(m.title ?? 'Review room'),
    url: typeof artifact === 'string' && artifact.startsWith('https://claude.ai/') ? artifact : null,   // only a room link
    cuts: cuts.filter(c => c?.file).length,
    sets: sets.length - boards.length,
    boards: boards.length,
    toMake: boards.filter(s => !cuts.find(c => c?.key === s.storyboardFor)?.file).map(s => title(s.storyboardFor!)),
    open: notes.filter(n => n?.status === 'open').length,
    fixed: notes.filter(n => n?.status === 'fixed').length,
    replies: notes.filter(waiting).length,
    todo: notes.filter(n => n?.status === 'open' || waiting(n)).length,
  }
}

const plural = (n: number, one: string, many = one + 's') => `${n} ${n === 1 ? one : many}`

async function refresh($: EngineInterface): Promise<void> {
  const r = await load($)
  await update($, room, () => r)
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => { const out = await next(e); await refresh($); return out })
  on('turn.complete', async ($, e, next) => { const out = await next(e); await refresh($); return out })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const r = await read($, room)
    if (!r || e.props.hasSurvey || (await read($, hidden))) return next(e)
    const { Box, Button, Link, Text } = $.ui.resolve(e)
    const send = (args: string) => () => { void $.command.run({ command: SKILL, args }).catch(() => $.ui.toast('The cut-review skill is not available here')) }
    const facts = [
      r.boards ? plural(r.boards, 'storyboard') : '',
      plural(r.cuts, 'cut'),
      r.sets ? plural(r.sets, 'set') : '',
      r.open ? `${r.open} open` : '',
      r.fixed ? `${r.fixed} to check` : '',
      r.replies ? `${plural(r.replies, 'reply', 'replies')} to answer` : '',
    ].filter(Boolean).join(' · ')
    const todo = r.todo   // a note open and with a reply counts once
    return (
      <Box flexDirection="row" flexWrap="wrap" gap={1}>
        <Text bold>{r.title}</Text>
        <Text dimColor>{facts}</Text>
        {todo
          ? <Button key="apply" label={`Apply ${plural(todo, 'note')}`} onPress={send(ASK.apply)} />
          : <Button key="check" label="Check notes" onPress={send(ASK.check)} />}
        {r.toMake[0] ? <Button key="make" label={`Make ${r.toMake[0]}`} onPress={send(ASK.make(r.toMake[0]))} /> : null}
        <Button key="plan" label="New video" onPress={send(ASK.plan)} />
        <Button key="update" label="Update room" onPress={send(ASK.update)} />
        {r.url ? <Link href={r.url} label="Open room" /> : null}
        <Button key="hide" label="Hide" onPress={() => update($, hidden, () => true)} />
      </Box>
    )
  })
}
