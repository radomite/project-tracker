# TeXlyre adaptations

The browser worker and package-registry integration are adapted from TeXlyre,
copyright its contributors, under AGPL-3.0-or-later.

Source: https://github.com/TeXlyre/texlyre
Revision: 697759981a2a7291fdd3855ea6e09cc6ca5c7723

Upstream files: src/extensions/typst.ts/typst-worker.ts,
TypstCompilerEngine.ts, TypstRendererRuntime.ts, and LongPathPackageRegistry.ts.
Adaptations: PDF-only output, same-origin assets, explicit source snapshots,
bounded worker lifetime, and integration with this application's file model.

The project file store, server WebSocket protocol, edit-window grouping, and
application view are implemented here. TeXlyre's P2P and browser-account systems
are not included. The compiler packages have their own Apache-2.0 notices.

The editable source for this integration is included with the application source
and is served through its Editor source download endpoint for network users.
