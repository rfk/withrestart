

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

Here's how the calling code would look if it wanted to silently skip the
missing file::

   def concatenate(dirname):
       with Handler(IOError,"skip"):
           data = readall(dirname)
       return "".join(data.itervalues())

This pushes a Handler instance into the execution context, which will detect
IOError instances and response by invoking the "skip" restart point.  If this
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


