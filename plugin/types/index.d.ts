// What the band above the prompt shows: the review room of the project the session is in, read from its files.
export type RoomInfo = {
  title: string
  url: string | null        // the room's claude.ai link, once published
  cuts: number              // cuts with a video
  sets: number              // carousels and other sets of stills and clips (not storyboards)
  boards: number            // storyboards
  toMake: string[]          // cuts whose storyboard is in the room but whose video isn't made yet
  open: number              // open notes, as of the last `cut-review notes`
  fixed: number             // fixed notes waiting for the owner to check
  replies: number           // notes with a reply from the owner Claude hasn't answered
  todo: number              // notes Claude has to act on: open, or waiting on an answer (each once)
}

declare module 'claude-code' {
  interface PluginState {
    'cut-review': { room: RoomInfo | null; hidden: boolean }
  }
}
