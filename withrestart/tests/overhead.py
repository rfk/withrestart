"""

  withrestart.tests.overhead:  functions for testing withrestart overhead

 
This module provides two simple functions "test_tryexcept" and "test_restart"
that are used to compare the overhead of a restart-based approach to a bare
try-except clause.
"""

from withrestart import *

def test_tryexcept(input,output):
    def endpoint(v):
        if v == 7:
            raise ValueError
        return v
    def callee(v):
        return endpoint(v)
    def caller(v):
        try:
            return callee(v)
        except ValueError:
            return 0
    assert caller(input) == output


def test_restart(input,output):
    def endpoint(v):
        if v == 7:
            raise ValueError
        return v
    def callee(v):
        with restarts(use_value) as invoke:
            return invoke(endpoint,v)
    def caller(v):
        with Handler(ValueError,"use_value",0):
            return callee(v)
    assert caller(input) == output


