# Third-party notices

The JARVIS mobile app ports animations of the JARVIS web frontend. Their code is derived from the projects below; each notice
is kept as the licence requires. Dart packages from pub.dev carry their own licences (see `flutter pub deps` / the licence page
that Flutter generates in the app).

## thinking-orbs (status orb) - MIT

`lib/chat/status_orb.dart` is a Dart port of the frame generators, presets and paint rules of `thinking-orbs/engine`
(https://github.com/Jakubantalik/Libraries.dev, `packages/thinking-orbs`).

```
MIT License

Copyright (c) 2026 Jakub Antalik

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software
is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## metal-fx (send-button halo) - MIT

`lib/chat/metal_send_button.dart` reproduces the glow recipe (layer strokes, blurs, core, colours) of metal-fx v2 by Libraries.dev
(https://libraries.dev/metal.html), (c) 2026 Jakub Antalik, under the same MIT licence text as above.

## morphicons (icon morph) - MIT

`lib/chat/morph_icon.dart` is a Dart port of the morphing core of morphicons 1.7.1 (https://github.com/guillermolg00/morphicons):
path parsing, cubic normalisation, equal-arc resampling, Procrustes planning, polar interpolation and the spring presets.

```
MIT License

Copyright (c) 2026 Guillermo

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software
is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR
IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Paper Shaders (liquid-metal ring) - Apache License 2.0

`shaders/liquid_metal.frag` is the liquid-metal fragment shader of Paper Shaders (https://github.com/paper-design/shaders,
https://shaders.paper.design), Copyright 2026 Paper, modified for Flutter's FragmentProgram: only the non-image circle path is kept,
the sizing of the vertex shader is folded in, screen-space derivatives are replaced by finite differences, a ring mask and a
round clip are added, and the output is premultiplied. Licensed under the Apache License, Version 2.0; you may obtain a copy at
http://www.apache.org/licenses/LICENSE-2.0. Unless required by applicable law or agreed to in writing, the software is distributed
on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific
language governing permissions and limitations.

## Lucide (icons) - ISC

The `send` and `check` path data in `lib/chat/morph_icon.dart` and the icon font of `lucide_icons_flutter` are from Lucide
(https://lucide.dev), Copyright (c) 2026 Lucide Icons and Contributors, ISC License.

## Lexend (welcome font) - SIL Open Font License 1.1

`assets/fonts/OFL.txt` ships with the font.
