# Media assets

| File | Use |
|---|---|
| `opengirgit-wordmark-dark.svg` | wordmark for **dark** backgrounds (light ink) |
| `opengirgit-wordmark-light.svg` | wordmark for **light** backgrounds (dark ink) |

The mark itself lives in [`packaging/org.opengirgit.OpenGirGit.svg`](../packaging/org.opengirgit.OpenGirGit.svg)
(one source for the Linux icon and the Windows `.ico`; see
[`packaging/README.md`](../packaging/README.md#icon)). The wordmarks are pure
outlines with no font dependency: the word *open* is Inter Bold converted to
paths, followed by the chameleon from the mark. The README swaps between the
two with `<picture>` + `prefers-color-scheme`.

The demo video and its poster frame will land in this folder as well.
