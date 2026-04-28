#!/usr/bin/env -S node --max-old-space-size=8192 --expose-gc

import { GatewayClient } from './gatewayClient.js'
import { setupGracefulExit } from './lib/gracefulExit.js'

const DEBUG = process.env.DEBUG === '1' || process.env.DEBUG === 'true'
const FORCE = process.env.FORCE_TTY === '1' || process.env.FORCE === '1'

const debug = (...args: unknown[]) => {
  if (DEBUG) console.error('[DEBUG]', ...args)
}

debug('TUI starting...')
debug('Environment:', {
  NOMAN_SRC_ROOT: process.env.NOMAN_SRC_ROOT,
  NOMAN_PYTHON_SRC_ROOT: process.env.NOMAN_PYTHON_SRC_ROOT,
  NOMAN_PYTHON: process.env.NOMAN_PYTHON,
  NOMAN_CWD: process.env.NOMAN_CWD,
  NOMAN_TUI_STARTUP_TIMEOUT_MS: process.env.NOMAN_TUI_STARTUP_TIMEOUT_MS,
})
debug('stdin isTTY:', process.stdin.isTTY, 'FORCE:', FORCE)

if (!process.stdin.isTTY && !FORCE) {
  console.log('noman-tui: no TTY')
  console.log('To run anyway: FORCE_TTY=1 pnpm start')
  process.exit(0)
}

const gw = new GatewayClient({
  pythonSrcRoot: process.env.NOMAN_SRC_ROOT ?? process.env.NOMAN_PYTHON_SRC_ROOT,
  python: process.env.NOMAN_PYTHON,
  cwd: process.env.NOMAN_CWD,
})

debug('Starting gateway client...')
gw.start()
debug('Gateway started')

setupGracefulExit({
  cleanups: [() => gw.kill()],
  onError: (scope, err) => {
    const message = err instanceof Error ? `${err.name}: ${err.message}` : String(err)
    process.stderr.write(`noman-tui ${scope}: ${message.slice(0, 2000)}\n`)
  },
  onSignal: signal => process.stderr.write(`noman-tui: received ${signal}\n`)
})

const [ink, { App }] = await Promise.all([
  import('@hermes/ink'),
  import('./app.js'),
])

ink.render(<App gw={gw} />, { exitOnCtrlC: false })