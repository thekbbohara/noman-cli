import { withInkSuspended } from '@hermes/ink'

import { launchHermesCommand, launchNomanCommand } from '../../../lib/externalCli.js'

export const SETUP_COMMANDS = [
  {
    name: 'setup',
    help: 'run full setup wizard (launches `noman setup`)',
    handler: async ({ transcript }) => {
      transcript.sys('launching `noman setup`…')
      const result = await launchNomanCommand(['setup'])
      if (result.error) {
        transcript.sys(`error launching noman: ${result.error}`)
      } else {
        transcript.sys(`noman setup exited with code ${result.code}`)
      }
    },
    launcher: launchNomanCommand,
    suspend: withInkSuspended
  }
]