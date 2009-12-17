"""

  withrestart.callstack:  class to manage per-call-stack context.

This module provides the CallStack class, which provides a simple stack-like
interface for managing additional context during the flow of execution.
Think of it like a thread-local stack with some extra smarts to account for
suspended generators etc.

To work correctly while mixing CallStack operations with generators, this
module requires a working implementation of sys._getframe().
 
"""


try:
    from sys import _getframe as _curframe
    _curframe()
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
        def _curframe():
            return _DummyFrame()
    except Exception:
        class _DummyFrame:
            f_back = None
        def _curframe():
            return _DummyFrame


class CallStack(object):
    """Class managed per-call-stack context information.

    Instances of this class can be used to manage a stack of addionnal
    information alongside the current execution stack.  They have the
    following methods:

        * push(item):  add an item to the stack for the current exec frame
        * pop(item):   pop an item from the stack for the current exec frame
        * items():     get iterator over stack of items for the current frame

    """

    def __init__(self):
        self._frame_stacks = {}

    def push(self,item,offset=0):
        """Push the given item onto the stack for current execution frame.

        If 'offset' is given, it is the number of execution frames to skip
        backwards before adding the item.
        """
        frame = _curframe()
        # We add one to the offset to account for this function call.
        while offset > -1 and frame.f_back is not None:
            frame = frame.f_back
            offset -= 1
        try:
            frame_stack = self._frame_stacks[frame]
        except KeyError:
            self._frame_stacks[frame] = frame_stack = []
        frame_stack.append(item)

    def pop(self):
        """Pop the top item from the stack for the current execution frame."""
        frame = _curframe()
        frame_stack = None
        while frame_stack is None:
            try:
                frame_stack = self._frame_stacks[frame]
            except KeyError:
                frame = frame.f_back
                if frame is None:
                    raise IndexError("stack is empty")
        frame_stack.pop()

    def items(self):
        """Iterator over stack of items for current execution frame."""
        frame = _curframe()
        while frame is not None:
            try:
                frame_stack = self._frame_stacks[frame]
            except KeyError:
                pass
            else:
                for item in reversed(frame_stack):
                    yield item
            frame = frame.f_back


