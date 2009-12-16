"""

  withrestart:  structured error recovery using named restart functions

This is a Pythonisation (lispers might rightly say "bastardisation") of the
restart-based condition system of Common Lisp.  It's designed to make error
recovery simpler and easier by removing the assumption that unhandled errors
must be fatal.

A "restart" represents a named strategy for resuming execution of a function
after the occurrence of an error.  At any point during its execution a
function can push a Restart object onto its call stack.  If an exception
occurs within the scope of that Restart, code higher-up in the call chain can
invoke it to recover from the error and let the function continue execution.
By providing several restarts, functions can offer several different strategies
for recovering from errors.

A "handler" represents a higher-level strategy for dealing with the occurrence
of an error.  It is conceptually similar to an "except" clause, in that one
establishes a suite of Handler objects to be invoked if an error occurs during
the execution of some code.  There is, however, a crucial difference: handlers
are executed without unwinding the call stack.  They thus have the opportunity
to take corrective action and then resume execution of whatever function
raised the error.

For example, consider a function that reads the contents of all files from a 
directory into a dictionary in memory::

   def readall(dirname):
       data = {}
       for filename in os.listdir(readall):
           filepath = os.path.join(dirname,filename)
           data[filename] = open(filepath).read()
       return data

If one of the files goes missing after the call to os.listdir() then the
subsequent open() will raise an IOError.  While we could catch and handle the
error inside this function, what would be the appropriate action?  Should
files that go missing be silently ignored?  Should they be re-created with
some default contents?  Should a special sentinel value be placed in the
data dictionary?  What value?  The readall() function does not have enough
information to decide on an appropriate recovery strategy.

Instead, readall() can provide the *infrastucture* for such recovery strategies
and leave the final decision up to the calling code.  The following definition
uses three pre-defined restarts to let the calling code (a) skip the missing
file completely, (2) retry the call to open() after taking some corrective
action, or (3) use some other value in place of the missing file::

   def readall(dirname):
       data = {}
       for filename in os.listdir(readall):
           filepath = os.path.join(dirname,filename)
           with restarts(skip,retry,use_value):
               data[filename] = invoke(open,filepath).read()
       return data

Of note here is the use of the "with" statement to establish a new context
in the scope of restarts, and use of the "invoke" wrapper when calling a
function that might fail.  The latter allows restarts to inject an alternate
return value for the failed function.

Here's how the calling code would look if it wanted to silently skip the
missing file::

   def concatenate(dirname):
       with Handler(IOError,"skip"):
           data = readall(dirname)
       return "".join(data.itervalues())

This pushes a Handler instance into the execution context, which will detect
IOError instances and respond by invoking the "skip" restart point.  If this
handler is invoked in response to an IOError, execution of the readall()
function will continue immediately following the "with restarts(...)" block.

Calling code that wanted to re-create the missing file would simply push
a different error handler::

   def concatenate(dirname):
       def handle_IOError(e):
           open(e.filename,"w").write("MISSING")
           invoke_restart("retry")
       with Handler(IOError,handle_IOError):
           data = readall(dirname)
       return "".join(data.itervalues())

Calling code that wanted to use a special sentinel value would use a handler
to pass the required value to the "use_value" restart::

   def concatenate(dirname):
       class MissingFile:
           def read():
               return "MISSING"
       def handle_IOError(e):
           invoke_restart("use_value",MissingFile())
       with Handler(IOError,handle_IOError):
           data = readall(dirname)
       return "".join(data.itervalues())


By separating the low-level details of recovering from an error from the
high-level stragegy of what action to take, it's possible to create quite
powerful recovery mechanisms.

While this module provides a handful of pre-built restarts, functions will
usualy want to create their own.  This can be done by passing a callback
into the Restart object constructor::

   def readall(dirname):
       data = {}
       for filename in os.listdir(readall):
           filepath = os.path.join(dirname,filename)
           def log_error():
               print "an error occurred"
           with Restart(log_error):
               data[filename] = open(filepath).read()
       return data


Or by using the @restarts.add decorator to define restarts inline::

   def readall(dirname):
       data = {}
       for filename in os.listdir(readall):
           filepath = os.path.join(dirname,filename)
           with restarts:
               @restarts.add
               def log_error():
                   print "an error occurred"
               data[filename] = open(filepath).read()
       return data

Handlers can also be defined inline using a similar syntax::

   def concatenate(dirname):
       with handlers:
           @handlers.add
           def IOError(e):
               open(e.filename,"w").write("MISSING")
               invoke_restart("retry")
           data = readall(dirname)
       return "".join(data.itervalues())


Now finally, a disclaimer.  I've never written any Common Lisp.  I've only read
about the Common Lisp condition system and how awesome it is.  I'm sure there
are many things that it can do that this module simply cannot.  Nevertheless,
there's no shame in trying to pinch a good idea when you see one...

"""

__ver_major__ = 0
__ver_minor__ = 1
__ver_patch__ = 0
__ver_sub__ = ""
__version__ = "%d.%d.%d%s" % (__ver_major__,__ver_minor__,
                              __ver_patch__,__ver_sub__)



#  The shared variable "_stack" is used to track per-thread stacks
#  of handlers and restarts.
try:
    import threading
except ImportError:
    class _stack:
        pass
else:
    _stack = threading.local()


class _NoValue:
    """Sentinel class; an alternative to None."""
    pass


class RestartError(Exception):
    """Base class for all user-visible exceptions raised by this module."""
    pass


class MissingRestartError(RestartError):
    """Exception raised when invoking a non-existent restart."""
    def __init__(self,name):
        self.name = name
    def __str__(self):
        return "No restart named '%s' has been defined" % (self.name,)


class RestartInvoked(Exception):
    """Exception raised to indicate that a restart was invoked.

    This is used as a flow-control mechanism and should never be seen
    by code outside this module.
    """
    def __init__(self,restart):
        self.restart = restart


class Restart(object):
    """Restart marker object.

    Instances of Restart represent named strategies for resuming execution
    after the occurrence of an error.  They push themselves onto the execution
    context when entered and pop themselves when exited.  If they are exited
    with an error, the any registered error handlers are invoked.
    """

    def __init__(self,func,name=None):
        self.func = func
        if name is None:
            self.name = func.func_name
        else:
            self.name = name

    def invoke(self,*args,**kwds):
        self.value = self.func(*args,**kwds)
        raise RestartInvoked(self)

    def __enter__(self):
        try:
            restarts = _stack.restarts
        except AttributeError:
            _stack.restarts = restarts = []
        restarts.append(self)
        return self

    def __exit__(self,exc_type,exc_value,traceback):
        try:
            if exc_type is not None:
                _invoke_handlers(exc_value)
                if _stack.invoked is self:
                    _stack.invoked = None
                    return True
                else:
                    return False
        finally:
            _stack.restarts.pop()


class Handler(object):
    """Restart handler object.

    Instances of Handler represent high-level control strategies for dealing
    with errors that have occurred.  They can be thought of as an "except"
    clause the executes at the site of the error instead of unwinding the
    stack.  Handlers push themselves onto the execution context when entered
    and pop themselves when exited.  They will not swallow errors, but
    can cause errors to be swallowed at a lower level of the callstack by
    explicitly invoking a restart.
    """

    def __init__(self,exc_type,func,*args,**kwds):
        """Handler object initialiser.

        Handlers must be initialised with an exception type (or tuple of
        types) and a function to be executed when such errors occur.  If
        the given function is a string, it names a restart that will be
        invoked immediately on error.

        Any additional args or kwargs will be passed into the handler
        function when it is executed.
        """
        self.exc_type = exc_type
        self.func = func
        self.args = args
        self.kwds = kwds

    def handle_error(self,e):
        if isinstance(e,self.exc_type):
            if isinstance(self.func,basestring):
                invoke_restart(self.func,*self.args,**self.kwds)
            else:
                self.func(e,*self.args,**self.kwds)

    def __enter__(self):
        try:
            handlers = _stack.handlers
        except AttributeError:
            _stack.handlers = handlers = []
        handlers.append(self)
        return self

    def __exit__(self,exc_type,exc_value,traceback):
        _stack.handlers.pop()


def invoke(func,*args,**kwds):
    """Invoke the given function, or return a value from a restart.

    This function can be used to invoke a function or callable object within
    the current restart context.  If the function runs to completion its
    result is returned.  If an error occurres, the handlers are executed and
    the result from any invoked restart becomes the return value of this
    function.

    The make a restart that does not trigger a return from invoke(), it
    should return the special object _NoValue.
    """
    try:
        calls = _stack.calls
    except AttributeError:
        _stack.calls = calls = []
    calls.append((func,args,kwds))
    try:
        return func(*args,**kwds)
    except Exception, e:
        _invoke_handlers(e)
        invoked = _stack.invoked
        if invoked is not None and invoked.value is not _NoValue:
            _stack.invoked = None
            return invoked.value
        else:
            raise
    finally:
        calls.pop()


def _invoke_handlers(err):
    """Invoke any defined handlers for the given error.

    If _stack.invoked is already set to a restart, this function will
    return immediately.  Otherwise it will invoke each handler in turn.
    If a handler invokes a restart, _stack.invoked is set to that restart
    and the function exits.
    """
    try:
        invoked = _stack.invoked
    except AttributeError:
        _stack.invoked = invoked = None
    if invoked is None:
        try:
            handlers = _stack.handlers
        except AttributeError:
            pass
        else:
            for handler in reversed(handlers):
                try:
                    handler.handle_error(err)
                except RestartInvoked, e:
                    _stack.invoked = e.restart
                    break


def find_restart(name):
    """Find a defined restart with the given name.

    If no such restart is found then MissingRestartError is raised.
    """
    try:
        restarts = _stack.restarts
    except AttributeError:
        raise MissingRestartError(name)
    else:
        for restart in reversed(restarts):
            if restart.name == name:
                return restart
        raise MissingRestartError(name)


def invoke_restart(name,*args,**kwds):
    """Invoke the named restart with the given arguments.

    If such a restart is defined then RestartInvoked will be raised;
    otherwise RestartError is raised.
    """
    find_restart(name).invoke(*args,**kwds)


def maybe_invoke_restart(name,*args,**kwds):
    """Invoke the named restart with the given arguments, if it exists.

    If such a restart is defined then RestartInvoked will be raised;
    otherwise the function exits silently.
    """
    try:
        find_restart(name).invoke(*args,**kwds)
    except MissingRestartError:
        pass



class restarts(Restart):
    """Class to easily combine multiple restarts into a single context."""

    def __init__(self,*restarts):
        self.restarts = [Restart(r) for r in restarts]
        self.name = None

    class _enter_descriptor(object):
        def __get__(self,obj,cls):
            if obj is None:
                return cls.__enter_class__
            else:
                return obj.__enter_instance__
    __enter__ = _enter_descriptor()

    class _exit_descriptor(object):
        def __get__(self,obj,cls):
            if obj is None:
                return cls.__exit_class__
            else:
                return obj.__exit_instance__
    __exit__ = _exit_descriptor()

    @classmethod
    def __enter_class__(cls):
        inst = cls()
        try:
            restarts = _stack.restarts
        except AttributeError:
            _stack.restarts = restarts = []
        restarts.append(inst)
        return inst.__enter__()

    @classmethod
    def __exit_class__(cls,*args):
        _stack.restarts[-1].__exit__(*args)

    @classmethod
    def add(cls,func):
        r = Restart(func)
        for inst in reversed(_stack.restarts):
            if isinstance(inst,cls):
                inst.restarts.append(r)
                r.__enter__()
                return func
        raise RestartError("no instance of restarts() found on stack")

    def __enter_instance__(self):
        try:
            restarts = _stack.restarts
        except AttributeError:
            _stack.restarts = restarts = []
        for r in self.restarts:
            restarts.append(r)
        return self

    def __exit_instance__(self,exc_type,exc_value,traceback):
        try:
            if exc_type is not None:
                _invoke_handlers(exc_value)
                for r in self.restarts:
                    if _stack.invoked is r:
                        _stack.invoked = None
                        return True
                else:
                    return False
        finally:
            for r in self.restarts:
                _stack.restarts.pop()

        

class handlers(Handler):
    """Class to easily combine multiple handlers into a single context."""

    def __init__(self,*handlers):
        self.handlers = ([Handler(*h) for h in handlers])

    def handle_error(self,e):
        pass

    class _enter_descriptor(object):
        def __get__(self,obj,cls):
            if obj is None:
                return cls.__enter_class__
            else:
                return obj.__enter_instance__
    __enter__ = _enter_descriptor()

    class _exit_descriptor(object):
        def __get__(self,obj,cls):
            if obj is None:
                return cls.__exit_class__
            else:
                return obj.__exit_instance__
    __exit__ = _exit_descriptor()

    @classmethod
    def __enter_class__(cls):
        inst = cls()
        inst = cls()
        try:
            handlers = _stack.handlers
        except AttributeError:
            _stack.handlers = handlers = []
        handlers.append(inst)
        return inst.__enter__()

    @classmethod
    def __exit_class__(cls,*args):
        _stack.handlers[-1].__exit__(*args)

    @staticmethod
    def _load_name(func,name):
        try:
            try:
                idx = func.func_code.co_cellvars.index(name)
            except ValueError:
                try:
                    idx = func.func_code.co_freevars.index(name)
                    idx -= len(func.func_code.co_cellvars)
                except ValueError:
                    raise NameError(name)
            return func.func_closure[idx].cell_contents
        except NameError:
            try:
                try:
                    return func.func_globals[name]
                except KeyError:
                    return __builtins__[name]
            except KeyError:
                raise NameError(name)

    @classmethod
    def add(cls,func=None,exc_type=None):
        def add_handler(func):
            if exc_type is None:
                h = Handler(cls._load_name(func,func.func_name),func)
            else:
                h = Handler(exc_type,func)
            for inst in reversed(_stack.handlers):
                if isinstance(inst,cls):
                    inst.handlers.append(h)
                    h.__enter__()
                    return func
            raise RestartError("no instance of handlers() found on stack")
        if func is None:
            return add_handler
        else:
            return add_handler(func)

    def __enter_instance__(self):
        for h in self.handlers:
            h.__enter__()

    def __exit_instance__(self,exc_type,exc_info,traceback):
        retval = None
        for h in self.handlers:
            retval = retval or h.__exit__(exc_type,exc_info,traceback)
        return retval


def use_value(value):
    """Pre-defined restart that returns the given value."""
    return value

def raise_error(error):
    """Pre-defined restart that raises the given error."""
    raise error

def skip():
    """Pre-defined restart that skips to the end of the restart context."""
    return _NoValue

def retry():
    """Pre-defined restart that retries the most-recently-invoked function."""
    (func,args,kwds) = _stack.calls[-1]
    return invoke(func,*args,**kwds)


