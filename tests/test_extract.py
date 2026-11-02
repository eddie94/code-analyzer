from textwrap import dedent

from codemap.extract import parse_source


def parse(code: str):
    return parse_source(dedent(code).encode())


def test_import_flags():
    info = parse("""
        from __future__ import annotations
        import os
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from a import A
        else:
            from b import B

        try:
            import ujson as json
        except ImportError:
            import json

        class C:
            import sys

        def f():
            from . import lazy
    """)
    by_name = {(i.module, i.alias): i for i in info.imports}
    assert ("__future__", None) not in by_name

    os_ = by_name["os", None]
    assert os_.module_level and not (os_.type_only or os_.lazy or os_.conditional)

    a = by_name["a", None]
    assert a.type_only and not a.conditional
    b = by_name["b", None]
    assert b.conditional and not b.type_only

    assert by_name["ujson", "json"].conditional
    assert by_name["json", None].conditional

    sys_ = by_name["sys", None]
    assert not sys_.module_level and not sys_.lazy

    lazy = by_name[None, None]
    assert lazy.lazy and lazy.level == 1 and lazy.names == [("lazy", None)]


def test_symbols():
    info = parse("""
        import abc

        @abc.abstractmethod
        def top():
            def nested():
                pass

        class Outer(abc.ABC, Generic[T], metaclass=Meta):
            class Inner:
                async def run(self):
                    pass
    """)
    symbols = {s.qualname: s for s in info.symbols}
    assert set(symbols) == {"top", "Outer", "Outer.Inner", "Outer.Inner.run"}
    assert symbols["top"].kind == "function"
    assert symbols["top"].decorators == ["abc.abstractmethod"]
    assert symbols["top"].range == (4, 7)
    assert symbols["Outer"].bases == [["abc", "ABC"], ["Generic"]]
    assert symbols["Outer.Inner.run"].kind == "method"
    assert symbols["Outer.Inner.run"].is_async
    assert info.defined == {"top", "Outer"}


def test_complexity():
    info = parse("""
        def f(xs):
            if not xs:
                return 0
            for x in xs:
                while x and x > 1 or x < -1:
                    x -= 1
            return [y for y in xs if y if y > 2]
    """)
    # 1 + if + for + while + `and`/`or` (2) + comprehension + 2 comprehension ifs
    assert info.symbols[0].complexity == 9


def test_loc_doc_and_all():
    info = parse('''
        """Module docstring.

        More text.
        """

        # comment

        __all__ = ["f"]


        def f():
            """Function docstring."""
            return 1
    ''')
    assert info.doc == "Module docstring."
    assert info.all_names == ["f"]
    assert info.loc == 3
    assert info.symbols[0].doc == "Function docstring."


def test_syntax_error():
    info = parse("def broken(:\n")
    assert info.error is not None and info.error.startswith("syntax error")
    assert info.error_line == 1
    assert info.symbols == []
