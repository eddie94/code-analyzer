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


def test_invalid_escape_does_not_warn(recwarn):
    info = parse(r"""
        PATTERN = "\{name\}"
    """)
    assert info.loc == 1
    assert not [w for w in recwarn if issubclass(w.category, SyntaxWarning)]


def test_calls_and_types():
    info = parse("""
        from typing import Optional

        class Service:
            client: "Client"

            def __init__(self, config: Optional[Config] = None, retries=Retry()) -> None:
                self.repo = Repo(config)
                self.session = None

            async def run(self, x: int) -> "Result":
                result = await self.repo.load(x)
                helper = make_helper()
                async with aiohttp.ClientSession() as session:
                    await session.post("/x")
                return super().run(x)
    """)
    symbols = {s.qualname: s for s in info.symbols}
    init = symbols["Service.__init__"]
    assert init.params["config"].annotation == ["Config"]
    assert init.params["retries"].call == ["Retry"]
    assert init.attrs["repo"][0].call == ["Repo"]
    assert "session" not in init.attrs  # `None` says nothing about the type
    assert symbols["Service"].attrs["client"][0].annotation == ["Client"]

    run = symbols["Service.run"]
    assert run.returns == ["Result"]
    calls = [(c.callee, c.awaited) for c in run.calls]
    assert (["self", "repo", "load"], True) in calls
    assert (["make_helper"], False) in calls
    assert (["session", "post"], True) in calls
    assert (["super", "run"], False) in calls
    assert run.locals["helper"][0].call == ["make_helper"]
    assert run.locals["session"][0].call == ["aiohttp", "ClientSession"]


def test_globals_and_module_variables():
    info = parse("""
        pool = None
        config: Settings = load()

        def connect():
            global pool
            pool = Pool(config)
    """)
    assert info.variables["config"][0].annotation == ["Settings"]
    assert info.variables["config"][0].call == ["load"]
    connect = info.symbols[0]
    assert connect.globals["pool"][0].call == ["Pool"]
    assert "pool" not in connect.locals


def test_entry_points():
    info = parse("""
        @app.post("/orders")
        async def create_order(): ...

        @router.route("/legacy", methods=["GET", "POST"])
        def legacy(): ...

        @app.on_event("startup")
        async def boot(): ...

        @cli.command()
        def build_index(): ...

        @app.get(path_var)
        def dynamic(): ...

        if __name__ == "__main__":
            uvicorn.run(app)
    """)
    entries = {s.qualname: [(e.kind, e.label) for e in s.entries] for s in info.symbols}
    assert entries["create_order"] == [("route", "POST /orders")]
    assert entries["legacy"] == [("route", "GET/POST /legacy")]
    assert entries["boot"] == [("startup", "on startup")]
    assert entries["build_index"] == [("command", "build-index")]
    assert entries["dynamic"] == []
    assert entries["__main__"] == [("main", "__main__")]
    main = next(s for s in info.symbols if s.qualname == "__main__")
    assert main.calls[0].callee == ["uvicorn", "run"]
    assert "__main__" not in info.defined


def test_call_chains():
    info = parse("""
        def f():
            make().run()
            make(1).client.send()
            (a or b).get()
            items[0].close()
    """)
    callees = [c.callee for c in info.symbols[0].calls if c.text != "make"]
    assert callees == [["make", "()", "run"], ["make", "()", "client", "send"], None, None]


def test_control_flow_context():
    info = parse("""
        async def restock(self, sku):
            # --- Validate ---
            if not sku:
                raise ValueError("empty sku")
            elif self.is_frozen(sku):
                return 0
            asyncio.create_task(self.audit(sku))
            ### Fetch ###
            while self.pending(sku):
                try:
                    async with lock(sku):
                        count, price = await asyncio.gather(self.count(sku), self.quote(sku))
                except KeyError:
                    log.warning("missing")
            return count * price
    """)
    fn = info.symbols[0]
    assert [(s.line, s.title) for s in fn.sections] == [(3, "Validate"), (9, "Fetch")]

    exits = [(e.kind, e.value, [(c.kind, c.text) for c in e.context]) for e in fn.exits]
    assert exits == [
        ("raise", "ValueError('empty sku')", [("if", "not sku")]),
        ("return", "0", [("else", "not sku"), ("if", "self.is_frozen(sku)")]),
        ("return", "count * price", []),
    ]

    calls = {c.text: c for c in fn.calls}
    assert [(c.kind, c.text) for c in calls["self.is_frozen"].context] == [("else", "not sku")]
    assert calls["self.pending"].context == []  # the loop condition runs outside the body
    gather = fn.calls.index(calls["asyncio.gather"])
    count = calls["self.count"]
    assert count.within == gather and calls["self.quote"].within == gather
    assert [(c.kind, c.text) for c in count.context] == [
        ("loop", "while self.pending(sku)"),
        ("with", "async with lock(sku)"),
    ]
    assert [(c.kind, c.text) for c in calls["log.warning"].context] == [
        ("loop", "while self.pending(sku)"),
        ("except", "except KeyError"),
    ]
    audit = calls["self.audit"]
    assert fn.calls[audit.within].text == "asyncio.create_task"
    assert calls["asyncio.create_task"].within is None
    assert "self" in fn.reads and "log" in fn.reads


def test_call_arguments_and_decorator_owner():
    info = parse("""
        @router.post("/x")
        def handler(): ...

        if __name__ == "__main__":
            uvicorn.run(app, host="0.0.0.0")
            uvicorn.run("pkg.main:app")
    """)
    assert info.symbols[0].entries[0].owner == ["router"]
    main = info.symbols[1]
    assert [c.args for c in main.calls] == [["app"], ['"pkg.main:app"']]


def test_section_headings():
    info = parse("""
        def f():
            ##########
            # Load   #
            ##########
            # just a note under the banner
            a()
            ### Save ###
            b()
            # --- Report ---
            c()
            # Step 4 done
            # 3 items left
            d()
    """)
    assert [s.title for s in info.symbols[0].sections] == ["Load", "Save", "Report", "Step 4 done"]


def test_call_results_assigned():
    info = parse("""
        async def f():
            rate, currency = convert(amount)
            total = await self.add_tax(rate)
            self.cache = build()
            notify(total)
    """)
    assert [(c.text, c.assigns) for c in info.symbols[0].calls] == [
        ("convert", ["rate", "currency"]),
        ("self.add_tax", ["total"]),
        ("build", []),
        ("notify", []),
    ]


def test_call_inputs_and_receiver():
    info = parse("""
        class Cart:
            def checkout(self, user, items):
                names = self.labels(user.strip())
                receipt = self.printer.render(names, lines=items.rows, width=PAGE.width)
                weight = sum(box for box in self.boxes if box)
                for row in items:
                    row.ship()
                schedule(self.notify(user))
                if not receipt:
                    return None
                return receipt, weight
    """)
    method = info.symbols[1]
    calls = {c.text: c for c in method.calls}
    # Only the function's own variables: no module globals (PAGE), no comprehension variables.
    assert calls["self.labels"].inputs == ["user"]
    assert calls["self.labels"].receiver is None
    assert calls["user.strip"].receiver == "user"
    assert calls["self.printer.render"].inputs == ["names", "items"]
    assert calls["self.printer.render"].receiver == "self.printer"
    assert calls["sum"].inputs == ["self.boxes"]
    assert calls["row.ship"].receiver == "row"  # bound by the for loop
    assert calls["schedule"].inputs == ["user"]  # the method passed along is not a value
    assert [e.inputs for e in method.exits] == [[], ["receipt", "weight"]]
