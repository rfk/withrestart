"""

  withrestart:  structured error recovery using named restart functions

This is a Pythonisation (Lispers might rightly say "bastardisation") of the
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
directory into a dict in memory::

   def readall(dirname):
       data = {}
       for filename in os.listdir(dirname):
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

Instead, readall() can provide the *infrastructure* for doing error recovery
and leave the final decision up to the calling code.  The following definition
uses three pre-defined restarts to let the calling code (a) skip the missing
file completely, (2) retry the call to open() after taking some corrective
action, or (3) use some other value in place of the missing file::

   def readall(dirname):
       data = {}
       for filename in os.listdir(dirname):
           filepath = os.path.join(dirname,filename)
           with restarts(skip,retry,use_value) as invoke:
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

Note that there is no way to achieve this skip-and-continue behaviour using an
ordinary try-except block; by the time the IOError has propagated up to the
concatenate() function for processing, all context from the execution of 
readall() will have been unwound and cannot be resumed.

Calling code that wanted to re-create the missing file would simply push a
different error handler::

   def concatenate(dirname):
       def handle_IOError(e):
           open(e.filename,"w").write("MISSING")
           raise InvokeRestart("retry")
       with Handler(IOError,handle_IOError):
           data = readall(dirname)
       return "".join(data.itervalues())

By raising InvokeRestart, this handler transfers control back to the restart
that was  established by the readall() function.  This particular restart
will re-execute the failing function call and let readall() continue with its
operation.

Calling code that wanted to use a special sentinel value would use a handler
to pass the required value to the "use_value" restart::

   def concatenate(dirname):
       class MissingFile:
           def read():
               return "MISSING"
       def handle_IOError(e):
           raise InvokeRestart("use_value",MissingFile())
       with Handler(IOError,handle_IOError):
           data = readall(dirname)
       return "".join(data.itervalues())


By separating the low-level details of recovering from an error from the
high-level strategy of what action to take, it's possible to create quite
powerful recovery mechanisms.

While this module provides a handful of pre-built restarts, functions will
usually want to create their own.  This can be done by passing a callback
into the Restart object constructor::

   def readall(dirname):
       data = {}
       for filename in os.listdir(dirname):
           filepath = os.path.join(dirname,filename)
           def log_error():
               print "an error occurred"
           with Restart(log_error):
               data[filename] = open(filepath).read()
       return data


Or by using a decorator to define restarts inline::

   def readall(dirname):
       data = {}
       for filename in os.listdir(dirname):
           filepath = os.path.join(dirname,filename)
           with restarts() as invoke:
               @invoke.add_restart
               def log_error():
                   print "an error occurred"
               data[filename] = open(filepath).read()
       return data

Handlers can also be defined inline using a similar syntax::

   def concatenate(dirname):
       with handlers() as h:
           @h.add_handler
           def IOError(e):
               open(e.filename,"w").write("MISSING")
               raise InvokeRestart("retry")
           data = readall(dirname)
       return "".join(data.itervalues())


Now finally, a disclaimer.  I've never written any Common Lisp.  I've only read
about the Common Lisp condition system and how awesome it is.  I'm sure there
are many things that it can do that this module simply cannot.  Nevertheless,
there's no shame in trying to pinch a good idea when you see one...

"""

__ver_major__ = 0
__ver_minor__ = 2
__ver_patch__ = 1
__ver_sub__ = ""
__version__ = "%d.%d.%d%s" % (__ver_major__,__ver_minor__,
                              __ver_patch__,__ver_sub__)



from withrestart.callstack import CallStack
_cur_restarts = CallStack()
_cur_handlers = CallStack()
_cur_calls = CallStack()


class NoValue:
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


class InvokeRestart(Exception):
    """Exception raised by handlers to invoke a selected restart.

    This is used as a flow-control mechanism and should never be seen by
    code outside this module.  It's purposely not a sublcass of RestartError;
    you really shouldn't be catching it except under special circumstances.
    """
    def __init__(self,restart,*args,**kwds):
        if not isinstance(restart,Restart):
            name = restart; restart = find_restart(name)
            if restart is None:
                raise MissingRestartError(name)
        self.restart = restart
        self.args = args
        self.kwds = kwds

    def invoke(self):
        return self.restart.invoke(*self.args,**self.kwds)


class Restart(object):
    """Restart marker object.

    Instances of Restart represent named strategies for resuming execution
    after the occurrence of an error.  Collections of Restart objects are
    pushed onto the execution context where code can cleanly restart after
    the occurrence of an error, but requires information from outside the
    function in order to do so.

    When an individual Restat object is used as a context manager, it will
    automatically wrap itself in a RestartSuite object.
    """

    def __init__(self,func,name=None):
        """Restart object initializer.

        A Restart must be initialized with a callback function to execute
        when the restart is invoked.  If the optional argument 'name' is
        given this becomes the name of the Restart; otherwise its name is
        taken from the callback function.
        """
        self.func = func
        if name is None:
            self.name = func.func_name
        else:
            self.name = name

    def invoke(self,*args,**kwds):
        return self.func(*args,**kwds)

    def __enter__(self):
        suite =  RestartSuite(self)
        _cur_restarts.push(suite,1)
        return suite

    def __exit__(self,exc_type,exc_value,traceback):
        _cur_restarts.items().next().__exit__(exc_type,exc_value,traceback)


class RestartSuite(object):
    """Class holding a suite of restarts belonging to a common context.

    The RestartSuite class is used to bundle individual Restart objects
    into a set that is pushed/popped together.  It's also possible to
    add and remove individual restarts from a suite dynamically, allowing
    them to be defined inline using decorator syntax.
    """

    def __init__(self,*restarts):
        self.restarts = []
        for r in restarts:
            if isinstance(r,RestartSuite):
                for r2 in r.restarts:
                    self.restarts.append(r2)
            elif isinstance(r,Restart):
                self.restarts.append(r)
            else:
                self.restarts.append(Restart(r))

    def add_restart(self,func=None,name=None):
        """Add the given function as a restart to this suite.

        If the 'name' keyword argument is given, that will be used instead
        of the name of the function.  The following are all equivalent:

            def my_restart():
                pass
            r.add_restart(Restart(my_restart,"skipit"))

            @r.add_restart(name="skipit")
            def my_restart():
                pass

            @r.add_restart
            def skipit():
                pass

        """
        def do_add_restart(func):
            if isinstance(func,Restart):
                r = func
            else:
                r = Restart(func,name)
            self.restarts.append(r)
            return func
        if func is None:
            return do_add_restart
        else:
            return do_add_restart(func)

    def del_restart(self,restart):
        """Remove the given restart from this suite.

        The restart can be specified as a Restart instance, function or name.
        """
        to_del = []
        for r in self.restarts:
            if r is restart or r.func is restart or r.name == restart:
                to_del.append(r)
        for r in to_del:
            self.restarts.remove(r)

    def __call__(self,func,*args,**kwds):
        _cur_calls.push((self,func,args,kwds))
        try:
            return func(*args,**kwds)
        except Exception, err:
            try:
                _invoke_cur_handlers(err)
            except InvokeRestart, e:
                if e.restart in self.restarts:
                    val = e.invoke()
                    if val is not NoValue:
                        return val
                raise
            else:
                raise
        finally:
            _cur_calls.pop()

    def __enter__(self):
        _cur_restarts.push(self,1)
        return self

    def __exit__(self,exc_type,exc_value,traceback):
        try:
            if exc_type is not None:
                if exc_type is InvokeRestart:
                    for r in self.restarts:
                        if exc_value.restart is r:
                            exc_value.invoke()
                            return True
                    else:
                        return False
                else:
                    try:
                        _invoke_cur_handlers(exc_value)
                    except InvokeRestart, e:
                        for r in self.restarts:
                            if e.restart is r:
                                e.invoke()
                                return True
                        else:
                            raise
                    else:
                        return False
        finally:
            _cur_restarts.pop()

#  Convenience name for accessing RestartSuite class.
restarts = RestartSuite


def find_restart(name):
    """Find a defined restart with the given name.

    If no such restart is found then None is returned.
    """
    for suite in _cur_restarts.items():
        for restart in suite.restarts:
            if restart.name == name:
                return restart
    return None



def invoke(func,*args,**kwds):
    """Invoke the given function, or return a value from a restart.

    This function can be used to invoke a function or callable object within
    the current restart context.  If the function runs to completion its
    result is returned.  If an error occurrs, the handlers are executed and
    the result from any invoked restart becomes the return value of this
    function.

    The make a restart that does not trigger a return from invoke(), it
    should return the special object NoValue.
    """
    _cur_calls.push((invoke,func,args,kwds))
    try:
        return func(*args,**kwds)
    except Exception, err:
        try:
            _invoke_cur_handlers(err)
        except InvokeRestart, e:
            val = e.invoke()
            if val is not NoValue:
                return val
            else:
                raise
        else:
            raise
    finally:
        _cur_calls.pop()


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
        """Handler object initializer.

        Handlers must be initialized with an exception type (or tuple of
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
        """Invoke this handler on the given error.

        This is a simple wrapper method to implement the shortcut syntax of
        passing the name of a restart directly into the handler.
        """
        if isinstance(e,self.exc_type):
            if isinstance(self.func,basestring):
                raise InvokeRestart(self.func,*self.args,**self.kwds)
            else:
                self.func(e,*self.args,**self.kwds)

    def __enter__(self):
        _cur_handlers.push(self,1)
        return self

    def __exit__(self,exc_type,exc_value,traceback):
        _cur_handlers.pop()


class HandlerSuite(object):
    """Class to easily combine multiple handlers into a single context.

    HandleSuite objects represent a set of Handlers that are pushed/popped
    as a group.  The suite can also have handlers dynamically added or removed,
    allowing then to be defined in-line using decorator syntax.
    """

    def __init__(self,*handlers):
        self.handlers = ([Handler(*h) for h in handlers])

    def handle_error(self,e):
        for h in self.handlers:
            h.handle_error(e)

    def __enter__(self):
        _cur_handlers.push(self,1)
        return self

    def __exit__(self,exc_type,exc_info,traceback):
        _cur_handlers.pop()

    def add_handler(self,func=None,exc_type=None):
        """Add the given function as a handler to this suite.

        If the given function is already a Handler object, it is used
        directly.  Otherwise, if the exc_type keyword argument is given,
        a Handler is created for that exception type.  Finally, if exc_type
        if not specified then is is looked up using the name of the given
        function.  Thus the following are all equivalent:

            def handle_IOError(e):
                pass
            h.add_handler(Handler(IOError,handle_IOError))

            @h.add_handler(exc_type=IOError):
            def handle_IOError(e):
                pass

            @h.add_handler
            def IOError(e):
                pass

        """
        def do_add_handler(func):
            if isinstance(func,Handler):
                h = func
            elif exc_type is None:
                h = Handler(_load_name_in_scope(func,func.func_name),func)
            else:
                h = Handler(exc_type,func)
            self.handlers.append(h)
            return func
        if func is None:
            return do_add_handler
        else:
            return do_add_handler(func)

    def del_handler(self,handler):
        """Remove any handlers matching the given value from the suite.

        The 'handler' argument can be a Handler instance, function or
        exception type.
        """
        to_del = []
        for h in self.handlers:
            if h is handler or h.func is handler or h.exc_type is handler:
                to_del.append(h)
        for h in to_del:
            self.handlers.remove(h)

#  Convenience name for accessing HandlerSuite class.
handlers = HandlerSuite


def _invoke_cur_handlers(err):
    """Invoke any defined handlers for the given error.

    Each handler is invoked in turn.  In the usual case one of the handlers
    will raise InvokeRestart and control will be transferred back to the
    function that raised the error.  If no handler invokes a restart then
    this function will exit normally; calling code should re-raise the
    original error.
    """
    for handler in _cur_handlers.items():
        handler.handle_error(err)



def use_value(value):
    """Pre-defined restart that returns the given value."""
    return value

def raise_error(error):
    """Pre-defined restart that raises the given error."""
    raise error

def skip():
    """Pre-defined restart that skips to the end of the restart context."""
    return NoValue

def retry():
    """Pre-defined restart that retries the most-recently-invoked function."""
    (invoke,func,args,kwds) = _cur_calls.items().next()
    return invoke(func,*args,**kwds)


def _load_name_in_scope(func,name):
    """Get the value of variable 'name' as seen in scope of given function.

    If no such variable is found in the function's scope, NameError is raised.
    """
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

