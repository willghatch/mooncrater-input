# Mooncrater Input

Mooncrater Input is an input translation system.

It was written with AI assistance based on my overall architecture plan and iterative guidance, but not much code review.
IE it is close to the “vibe coding” end of the AI usage spectrum.
I wrote it for personal use, including various features that I don't really use but wanted for demo purposes (so they may not work very well for serious use), and am publishing it primarily for personal convenience.
But feel free to use it if you find it useful.

It is similar to [Kanata](https://github.com/jtroo/kanata), or like [QMK](https://qmk.fm/) except running on the OS instead of on a keyboard microcontroller.

So if it's similar to other things that already exist, and that I already have used, why did I make it?

## 1 - basically, it is more programmable

Mooncrater input in basically a python library, and the configuration is the program that loads it.
Sort of like an [Xmonad](https://xmonad.org/) kind of vibe.
So the configuration is just arbitrary Python code that you write, and Mooncrater Input provides the core libraries.

## 2 - json events

One of the problems with OS keyboard systems, is that they are too rigid.
They were designed for the computationally impoverished days of yore, when memory was at a premium.
They have small sets of possible events.
They are stingy with modifiers.
They are inflexible.
They are buggy for use cases that fall out of the norm.
But real keyboard events are incredibly low bandwidth.
If you type at 200 words-per-minute, that is extremely fast, but is only 1000 characters per minute, or 2000 key events per minute.
Per minute.
On a processor who's clock speed is measured in GHz.
Keyboard events can afford to be much larger.
This argument works less well, but still pretty well, for other input events.
They should be much richer.

Anyway, mooncrater basically translates all supported events into json objects.
Internally, arbitrary json objects can be used, and custom code can handle whatever.
User code is an arbitrary computer program, so it can do whatever it wants with those events.
Normally, you maybe want to implement custom keyboard logic to make custom key maps, or have new kinds of modifiers with custom state machines.
You can bind events to launch programs or send messages, eg. to your window manager.
You can have it act like a KVM and re-route keyboard events.
You can interpose and change things that are numeric, like mouse movement or scroll velocity.
You can maybe even track mouse movements to read gestures, though I don't think I'll go that far.
You can do whatever.

In practice, I wanted things including new multi-stage key bindings, the ability to change mappings for different active programs (at the time of writing, I still haven't actually done that, but it's possible in theory by cooperating with the window manager), and custom mouse event handling.
Maybe the most interesting demo that I've implemented and actually use is to bind an extra mouse button (beyond the few that are typically actually used for useful purposes) so that when it is held down it replaces mouse movement events to send 2d scroll events instead.
Also when that mouse button is down, it turns the actual scroll wheel into a mouse speed multiplier adjustment, which is also nice in theory but in practice I don't seem to use it much.

When using XKB, the most flexible of the OS keyboard drivers, it is still limited in modifier keys, which are shared between shift-like functionality (adding layers to the keyboard, in QMK terms) and control-like functionality (modifiers typically used for binding “keyboard shortcuts” and typically ignored when not bound).
Using Mooncrater Input on top of XKB lets me use more of them as control-like modifiers instead of shift-like modifiers.
(Why would you want more modifiers?  Well, among other things, it lets you use different modifiers for different semantic groups of actions.  Maybe I won't bind every letter with every modifier and use the full space of possible bindings, but I can more easily remember bindings that are more semantically grouped by different modifiers or modifier combinations.)

## more technical stuff

Some basic technical info to give some idea.
But I haven't written any real documentation and probably won't.
Look at the source code, or have an AI do it.

### Example JSON Events

A key press and a mouse movement from a captured device look like:

```json
{"category": "keyboard", "type": "keyDown", "scancode": 30, "keyName": "KEY_A", "keyChar": "a", "inputTag": "main-kbd", "inputKind": "capturedDevice", "device": "main-kbd", "evdev-unix-seconds": 1718900000.123}
{"category": "mouse", "type": "mouseRel", "deltaX": 5, "deltaY": -3, "inputTag": "main-trackball", "inputKind": "capturedDevice", "device": "right-trackball", "evdev-unix-seconds": 1718900000.456}
```

#### Common fields (present in every event)

- **`inputTag`** — the tag you assigned to the source device or input channel -- useful for filtering events, handling different devices separately, adding policy to socket events, etc.
- **`inputKind`** — how the event arrived: `capturedDevice`, `unixDomainSocket`, ...
- **`category`** — broad grouping: `keyboard`, `mouse`, `touchpad`, `unknown`, `command`, ...
- **`type`** — what happened: `keyDown`, `keyUp`, `keyRepeat`, `mouseDown`, `mouseUp`, `mouseRel`, `scroll`, `smoothScroll`, `eventList`, ...

#### Event-specific fields

- **`keyName`**, **`keyChar`**, **`scancode`** — keyboard events.  Incoming events from real hardware have all of them, outgoing events need only one.  There is some order of precedence if they disagree.
- **`button`** — mouse button events (`left`, `right`, `middle`, `back`, `forward`)
- **`deltaX`**, **`deltaY`** — mouse movement, scroll, and smooth-scroll events (floats for `smoothScroll`)
- **`rawDeltaX`**, **`rawDeltaY`** — raw evdev units for `smoothScroll` (~120 = one notch)
- **`events`** — array of sub-events for `eventList` type
- There are various others, and you can make up arbitrary events when you put them through a socket or something.
