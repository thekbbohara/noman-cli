import { withInkSuspended } from '@hermes/ink'

import { launchNomanCommand } from '../../../lib/externalCli.js'

    help: 'run full setup wizard (launches `noman setup`)',

        launcher: launchNomanCommand,
        suspend: withInkSuspended
      })
  }
]
