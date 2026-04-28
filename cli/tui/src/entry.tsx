#!/usr/bin/env -S node --max-old-space-size=8192 --expose-gc

import { GatewayClient } from './gatewayClient.js'
import { setupGracefulExit } from './lib/gracefulExit.js'

if (!process.stdin.isTTY) {
  console.log('noman-tui: no TTY')
  process.exit(0)
}

const gw = new GatewayClient({
  pythonSrcRoot: process.env.NOMAN_SRC_ROOT ?? process.env.NOMAN_PYTHON_SRC_ROOT,
  python: process.env.NOMAN_PYTHON,
  cwd: process.env.NOMAN_CWD,
})

gw.start()

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