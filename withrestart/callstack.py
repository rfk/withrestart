"""

  withrestart.callstack:  class to manage per-call-stack context.

This module provides the CallStack class, which provides a simple stack-like
interface for managing additional context during the flow of execution.
Think of it like a thread-local stack with some extra smarts to account for
suspended generators etc.

To work correctly while mixing CallStack operations with generators, this
module requires a working implementation of sys._getframe().
 
"""

import sys

try:
    from sys import _getframe
    _getframe()
except Exception:
    try:
        import threading
        class _DummyFrame:
            f_back = None
            def __init__(self):
                self.thread = threading.currentThread()
            def __hash__(self):
                return hash(self.thread)
            def __eq__(self,other):
                return self.thread == other.thread
        def _getframe(n=0):
            return _DummyFrame()
    except Exception:
        class _DummyFrame:
            f_back = None
        def _getframe(n=0):
            return _DummyFrame


def enable_psyco_support():
    """Enable support for psyco's simulated frame objects.

    This function patches psyco's simulated frame objects to be usable
    as dictionary keys, and switches internal use of _getframe() to use
    the version provided by psyco.
    """
    global _getframe
    import psyco.support
    psyco.support.PythonFrame.__eq__ = lambda s,o: s._frame == o._frame
    psyco.support.PythonFrame.__hash__ = lambda self: hash(self._frame)
    psyco.support.PsycoFrame.__eq__ = lambda s,o: s._tag[2] == o._tag[2]
    psyco.support.PsycoFrame.__hash__ = lambda self: hash(self._tag[2])
    _getframe = psyco.support._getframe


if "psyco" in sys.modules:
    enable_psyco_support()


class CallStack(object):
    """Class managing per-call-stack context information.

    Instances of this class can be used to manage a stack of addionnal
    information alongside the current execution stack.  They have the
    following methods:

        * push(item):  add an item to the stack for the current exec frame
        * pop(item):   pop an item from the stack for the current exec frame
        * items():     get iterator over stack of items for the current frame

    """

    def __init__(self):
        self._frame_stacks = {}

    def __len__(self):
        return len(self._frame_stacks)

    def clear(self):
        self._frame_stacks.clear()

    def push(self,item,offset=0):
        """Push the given item onto the stack for current execution frame.

        If 'offset' is given, it is the number of execution frames to skip
        backwards before adding the item.
        """
        # We add one to the offset to account for this function call.
        frame = _getframe(offset+1)
        try:
            frame_stack = self._frame_stacks[frame]
        except KeyError:
            self._frame_stacks[frame] = frame_stack = []
        frame_stack.append(item)

    def pop(self):
        """Pop the top item from the stack for the current execution frame."""
        frame = _getframe(1)
        frame_stack = None
        while frame_stack is None:
            try:
                frame_stack = self._frame_stacks[frame]
            except KeyError:
                frame = frame.f_back
                if frame is None:
                    raise IndexError("stack is empty")
        frame_stack.pop()
        if not frame_stack:
            del self._frame_stacks[frame]

    def items(self):
        """Iterator over stack of items for current execution frame."""
        frame = _getframe(1)
        while frame is not None:
            try:
                frame_stack = self._frame_stacks[frame]
            except KeyError:
                pass
            else:
                for item in reversed(frame_stack):
                    yield item
            frame = frame.f_back


