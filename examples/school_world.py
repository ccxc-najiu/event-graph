"""Run from the repository root: python3 -m examples.school_world."""

from eventgraph import Connection, Event, EventGraph, History, InputKind, Result, TableFlow


def main():
    graph = EventGraph()
    history = History()
    graph.append(
        events=[
            Event("admission", ("candidate_a", "candidate_b", "examiner"),
                  TableFlow(default={"admission.pass", "admission.fail", "admission.examined"})),
            Event("final", ("student", "teacher"), TableFlow(default={"final.high"})),
            Event("job", ("applicant", "interviewer"), TableFlow(
                {frozenset({"final.high"}): {"job.hired", "job.interviewed"}},
                default={"job.rejected", "job.interviewed"},
            )),
        ],
        results=[
            Result("admission.pass", "admission", ("candidate_a",)),
            Result("admission.fail", "admission", ("candidate_b",)),
            Result("admission.examined", "admission", ("examiner",)),
            Result("final.high", "final", ("student",)),
            Result("job.hired", "job", ("applicant",)),
            Result("job.rejected", "job", ("applicant",)),
            Result("job.interviewed", "job", ("interviewer",)),
        ],
        connections=[
            Connection("admission.pass", "final", InputKind.TRIGGER, "student"),
            Connection("final.high", "job", InputKind.RELATED, "applicant"),
        ],
    )
    graph.execute("admission", history, participants={
        "candidate_a": "甲", "candidate_b": "乙", "examiner": "丙",
    }, time=1, location="学校")
    print("乙能参加期末考试：", graph.is_enabled(
        "final", history, participants={"student": "乙", "teacher": "丁"}, time=2, location="学校"
    ))
    graph.execute("final", history, participants={"student": "甲", "teacher": "丁"}, time=2, location="学校")

    # Add an independent event and explicitly describe its effect on job's process.
    report = graph.append(
        events=[Event("apprenticeship", ("worker",), TableFlow(default={"work.experience"}))],
        results=[Result("work.experience", "apprenticeship", ("worker",))],
        connections=[Connection("work.experience", "job", InputKind.RELATED, "applicant")],
        flow_updates={"job": TableFlow({
            frozenset({"final.high"}): {"job.hired", "job.interviewed"},
            frozenset({"work.experience"}): {"job.hired", "job.interviewed"},
            frozenset({"final.high", "work.experience"}): {"job.hired", "job.interviewed"},
        }, default={"job.rejected", "job.interviewed"})},
    )
    print("append 后更新的已有事件：", sorted(report.updated_events))
    graph.execute("apprenticeship", history, participants={"worker": "乙"}, time=3, location="工坊")
    graph.execute("job", history, participants={"applicant": "乙", "interviewer": "戊"}, time=4, location="公司")
    for person in ("甲", "乙", "丙", "戊"):
        print(person, "的结果经历：", [r.result_id for r in history.for_actor(person)])

    # Replacing a port does not rewrite the already-recorded final.high result.
    graph.replace_result(
        "final.high", Result("final.excellent", "final", ("student",)),
        connections=[Connection("final.excellent", "job", InputKind.RELATED, "applicant")],
        flow_updates={
            "final": TableFlow(default={"final.excellent"}),
            "job": TableFlow({
                frozenset({"final.excellent"}): {"job.hired", "job.interviewed"},
                frozenset({"work.experience"}): {"job.hired", "job.interviewed"},
                frozenset({"final.excellent", "work.experience"}): {"job.hired", "job.interviewed"},
            }, default={"job.rejected", "job.interviewed"}),
        },
    )
    print("当前期末考试输出定义：", sorted(graph.schema("final").outputs))
    print("甲的历史仍保留旧结果：", [r.result_id for r in history.for_actor("甲")])


if __name__ == "__main__":
    main()
