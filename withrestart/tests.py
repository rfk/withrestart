
from __future__ import with_statement

import os
import unittest
import threading

import withrestart
from withrestart import *


def div(a,b):
    return a/b

class TestRestarts(unittest.TestCase):
    """Testcases for the "withrestart" module."""

    def test_basic(self):
        def handle_TypeError(e):
            invoke_restart("use_value",7)
        with Handler(TypeError,handle_TypeError):
            with Restart(use_value):
                self.assertEquals(div(6,3),2)
                self.assertEquals(invoke(div,6,3),2)
                self.assertEquals(invoke(div,6,"2"),7)

    def test_multiple(self):
        def handle_TE(e):
            invoke_restart("use_value",7)
        def handle_ZDE(e):
            invoke_restart("raise_error",RuntimeError)
        with handlers((TypeError,handle_TE),(ZeroDivisionError,handle_ZDE)):
            with restarts(use_value,raise_error):
                self.assertEquals(div(6,3),2)
                self.assertEquals(invoke(div,6,3),2)
                self.assertEquals(invoke(div,6,"2"),7)
                self.assertRaises(RuntimeError,invoke,div,6,0)

    def test_nested(self):
        with Handler(TypeError,"use_value",7):
            with restarts(use_value):
                self.assertEquals(div(6,3),2)
                self.assertEquals(invoke(div,6,3),2)
                self.assertEquals(invoke(div,6,"2"),7)
                with Handler(TypeError,"use_value",9):
                    self.assertEquals(invoke(div,6,"2"),9)
                self.assertEquals(invoke(div,6,"2"),7)
                self.assertRaises(ZeroDivisionError,invoke,div,6,0)
                with handlers((ZeroDivisionError,"raise_error",RuntimeError)):
                    self.assertRaises(MissingRestartError,invoke,div,6,0)
                    with Restart(raise_error):
                        self.assertEquals(div(6,3),2)
                        self.assertEquals(invoke(div,6,3),2)
                        self.assertEquals(invoke(div,6,"2"),7)
                        self.assertRaises(RuntimeError,invoke,div,6,0)


    def test_skip(self):
        def calculate(i):
            if i == 7:
                raise ValueError("7 is not allowed")
            return i
        def aggregate(items):
            total = 0
            for i in items:
                with restarts(skip,use_value):
                    total += invoke(calculate,i)
            return total
        self.assertEquals(aggregate(range(6)),sum(range(6)))
        self.assertRaises(ValueError,aggregate,range(8))
        with Handler(ValueError,"skip"):
            self.assertEquals(aggregate(range(8)),sum(range(8)) - 7)
        with Handler(ValueError,"use_value",9):
            self.assertEquals(aggregate(range(8)),sum(range(8)) - 7 + 9)

    def test_threading(self):
        def calc(a,b):
            with restarts(use_value):
                return invoke(div,a,b)
        evt1 = threading.Event()
        evt2 = threading.Event()
        evt3 = threading.Event()
        errors = []
        def thread1():
            try:
                self.assertRaises(TypeError,calc,6,"2")
                with Handler(TypeError,"use_value",4):
                    self.assertEquals(calc(6,"2"),4)
                    evt1.set()
                    evt2.wait()
                    self.assertEquals(calc(6,"2"),4)
                    evt3.set()
                self.assertRaises(TypeError,calc,6,"2")
            except Exception, e:
                evt1.set()
                evt3.set()
                errors.append(e)
        def thread2():
            try:
                self.assertRaises(TypeError,calc,6,"2")
                evt1.wait()
                self.assertRaises(TypeError,calc,6,"2")
                with Restart(raise_error):
                    self.assertRaises(TypeError,calc,6,"2")
                    with Handler(TypeError,"raise_error",ValueError):
                        self.assertRaises(ValueError,calc,6,"2")
                        evt2.set()
                        evt3.wait()
                        self.assertRaises(ValueError,calc,6,"2")
                    self.assertRaises(TypeError,calc,6,"2")
                self.assertRaises(TypeError,calc,6,"2")
            except Exception, e:
                evt2.set()
                errors.append(e)
        t1 = threading.Thread(target=thread1)
        t2 = threading.Thread(target=thread2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        for e in errors:
            raise e

    def test_inline_definitions(self):
        with handlers:
            @handlers.add
            def TypeError(e):
                invoke_restart("my_use_value",7)
            with restarts:
                @restarts.add
                def my_use_value(v):
                    return v
                self.assertEquals(div(6,3),2)
                self.assertEquals(invoke(div,6,3),2)
                self.assertEquals(invoke(div,6,"2"),7)
                self.assertRaises(ZeroDivisionError,invoke,div,6,0)
                @restarts.add
                def my_raise_error(e):
                    raise e
                self.assertRaises(ZeroDivisionError,invoke,div,6,0)
                @handlers.add(exc_type=ZeroDivisionError)
                def handle_ZDE(e):
                    invoke_restart("my_raise_error",RuntimeError)
                self.assertRaises(RuntimeError,invoke,div,6,0)

    def test_retry(self):
        call_count = {}
        def callit(v):
            if v not in call_count:
                call_count[v] = v
            else:
                call_count[v] -= 1
            if call_count[v] > 0:
                raise ValueError("call me again")
            return v
        self.assertRaises(ValueError,callit,2)
        self.assertRaises(ValueError,callit,2)
        self.assertEquals(callit(2),2)
        errors = []
        with handlers:
            @handlers.add(exc_type=ValueError)
            def OnValueError(e):
                errors.append(e)
                invoke_restart("retry")
            with restarts(retry):
                self.assertEquals(invoke(callit,3),3)
        self.assertEquals(len(errors),3)


    def test_README(self):
        """Ensure that the README is in sync with the docstring.

        This test should always pass; if the README is out of sync it just
        updates it with the contents of withrestart.__doc__.
        """
        dirname = os.path.dirname
        readme = os.path.join(dirname(dirname(__file__)),"README.txt")
        if not os.path.isfile(readme):
            f = open(readme,"wb")
            f.write(withrestart.__doc__)
            f.close()
        else:
            f = open(readme,"rb")
            if f.read() != withrestart.__doc__:
                f.close()
                f = open(readme,"wb")
                f.write(withrestart.__doc__)
                f.close()


