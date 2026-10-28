# Specifications

PhotoFinish is developed spec-first for changes to its file formats, what the referee sees
and how it works with the other timing tools, with
[Spec Kit](https://github.com/github/spec-kit), whose skills both coding agents here
(Claude Code and Codex) carry.

```
specs/
  app/                        the program as it works today, from the first feature on
  <NNN>-<short-name>/         one feature
    spec.md                   what and why, for the referee and the readers of the files
    plan.md, tasks.md         how it will be built, once the spec is reviewed
```

The principles every plan is checked against are in
[`.specify/memory/constitution.md`](../.specify/memory/constitution.md).

**Keep `app/` true.** A change that alters described behaviour updates it in the same pull
request.
