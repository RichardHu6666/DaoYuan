import datetime
import json
import sqlite3

DB_PATH = "/root/if_land_web-v2/seu_campus_assistant.db"


def course(local_id, code, name, day, start, end, location, teacher, weeks, note, color):
    return {
        "local_id": local_id,
        "course_id": code,
        "course_name": name,
        "day_of_week": str(day),
        "start_section": str(start),
        "end_section": str(end),
        "start_time": str(start),
        "end_time": str(end),
        "location": location,
        "teacher": teacher,
        "weeks": weeks,
        "note": note,
        "color": color,
    }


USERS = {
    "test_linyiran": {
        "uuid": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0001",
        "nickname": "林一然",
        "gender": "女",
        "birthday": "2007-03-18",
        "major": "计算机科学与技术",
        "enrollment_year": 2025,
        "interest": ["人工智能", "算法竞赛", "校园信息化", "开源项目", "机器学习", "全栈开发"],
        "profile": {
            "real_name": "林一然",
            "campus": "九龙湖",
            "college": "计算机科学与工程学院",
            "grade": "大一",
            "goals": ["参加AI竞赛", "提升GPA", "加入实验室", "完成一个能展示的开源项目"],
            "preferences": {
                "interests": ["人工智能", "算法竞赛", "校园信息化", "开源项目", "机器学习", "全栈开发"],
                "goals": ["竞赛", "科研", "奖学金", "开源贡献"],
                "campus": "九龙湖",
                "preferred_notice_types": ["竞赛报名", "科研招募", "技术讲座", "奖学金通知"],
                "avoid": ["纯行政通知", "与本科生无关的研究生通知"],
                "response_style": "先给结论，再给截止时间和下一步操作",
            },
            "personal_description": "计算机大一学生，想把课程项目和AI竞赛结合起来。对算法、机器学习、校园工具和开源项目感兴趣，希望系统优先筛选近期能报名、适合低年级参加、能形成作品集的机会。",
            "assistant_persona": "直接、短句、带优先级。遇到竞赛信息时请给出报名截止、组队建议和准备清单。",
        },
        "schedule": {
            "1": [
                course("lin-cs101", "CS101", "程序设计基础", 1, 1, 2, "教一-201", "王老师", "1-16", "带电脑，课后有OJ练习", "blue"),
                course("lin-linear", "MATH121", "线性代数", 1, 6, 7, "纪忠楼-205", "周老师", "1-16", "重点复习矩阵分解", "green"),
            ],
            "2": [
                course("lin-math", "MATH102", "高等数学A", 2, 3, 4, "纪忠楼-103", "李老师", "1-16", "周二交作业", "green"),
                course("lin-english", "ENG101", "大学英语", 2, 8, 9, "外语楼-302", "沈老师", "1-16", "第12周presentation", "rose"),
            ],
            "3": [course("lin-ai", "AI100", "人工智能导论", 3, 6, 7, "计算机楼-报告厅", "陈老师", "3-14", "小组展示", "violet")],
            "4": [course("lin-discrete", "CS120", "离散数学", 4, 1, 2, "教三-110", "赵老师", "1-16", "每两周一次小测", "amber")],
            "5": [course("lin-pe", "PE101", "羽毛球", 5, 8, 9, "体育馆", "赵老师", "1-12", "带球拍", "orange")],
            "6": [],
            "7": [],
        },
        "plans": [
            ("蓝桥杯校内报名确认", "竞赛", "2026-06-08 09:00", "2026-06-08 23:00", "2026-06-08 20:00", "todo", 3, "检查报名表、队友信息和缴费状态。"),
            ("AI导论小组展示PPT", "课程", "2026-06-09 19:00", "2026-06-10 12:00", "2026-06-09 21:00", "doing", 2, "整理Demo截图、方法流程图和3分钟讲解稿。"),
            ("实验室开放日申请", "科研", "2026-06-12 10:00", "2026-06-12 18:00", "2026-06-12 09:00", "todo", 2, "关注学院官网通知，准备自我介绍和项目经历。"),
            ("高数第十五周作业", "作业", "2026-06-06 18:00", "2026-06-09 23:00", "2026-06-09 20:30", "todo", 2, "完成多元函数部分习题，拍照上传学习平台。"),
            ("开源项目README重写", "项目", "2026-06-07 14:00", "2026-06-11 22:00", "2026-06-10 21:00", "doing", 3, "把Campus工具Demo整理成可展示README。"),
            ("算法周赛复盘", "竞赛", "2026-06-10 20:00", "2026-06-10 23:30", "2026-06-10 19:30", "todo", 4, "复盘动态规划题和图论题，记录错因。"),
            ("奖学金材料初筛", "事务", "2026-06-14 09:00", "2026-06-15 18:00", "2026-06-14 10:00", "todo", 3, "整理成绩单、竞赛证明和志愿时长。"),
        ],
        "notifications": [
            ("news", "AI竞赛与算法比赛", "关键词：人工智能、机器学习、算法竞赛、挑战杯、蓝桥杯、创新创业。优先推送本科生可报名、截止时间在30天内的通知。", "daily", None, None, ["08:20", "21:30"]),
            ("news", "科研招募与实验室开放", "关键词：实验室开放日、科研助理、本科生科研、导师招募、项目训练。", "daily", None, None, ["12:20"]),
            ("fixed", "每日DDL总览", "每天早上汇总今日待办、三天内截止事项和课程冲突。", "daily", None, None, ["08:00"]),
            ("news", "开源社区活动", "关键词：ModelScope、GitHub、开源贡献、技术沙龙、开发者活动。", "weekly", 3, None, ["18:30"]),
        ],
    },
    "test_chenmoyun": {
        "uuid": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0002",
        "nickname": "陈墨云",
        "gender": "男",
        "birthday": "2006-11-07",
        "major": "建筑学",
        "enrollment_year": 2024,
        "interest": ["城市设计", "生成式AI", "展览讲座", "学生组织", "设计竞赛", "作品集"],
        "profile": {
            "real_name": "陈墨云",
            "campus": "四牌楼",
            "college": "建筑学院",
            "grade": "大二",
            "goals": ["找到设计竞赛", "跟踪讲座展览", "管理课程DDL", "完善作品集"],
            "preferences": {
                "interests": ["城市设计", "生成式AI", "展览讲座", "学生组织", "设计竞赛", "作品集"],
                "goals": ["竞赛", "讲座", "作品集", "学生组织"],
                "campus": "四牌楼",
                "preferred_notice_types": ["讲座论坛", "设计竞赛", "展览活动", "学院通知"],
                "avoid": ["纯理工科研招募", "九龙湖远距离临时活动"],
                "response_style": "按地点、时间、报名动作排序",
            },
            "personal_description": "建筑学大二学生，平时信息来源分散在学院公众号、展览通知、竞赛平台和学生组织群。希望系统把设计竞赛、城市更新讲座、作品集相关活动筛出来，并提醒模型作业和评图节点。",
            "assistant_persona": "像项目助理一样给清单，强调时间地点、材料准备和是否值得去。",
        },
        "schedule": {
            "1": [course("chen-design", "ARCH201", "建筑设计基础", 1, 3, 5, "中大院-设计教室", "周老师", "1-18", "每周评图，带草图本", "teal")],
            "2": [
                course("chen-structure", "ARCH215", "建筑结构概论", 2, 1, 2, "前工院-301", "吴老师", "1-16", "第10周小测", "blue"),
                course("chen-digital", "ARCH230", "数字建模", 2, 6, 8, "机房B-204", "唐老师", "3-15", "Rhino/Grasshopper", "violet"),
            ],
            "3": [course("chen-history", "HIS203", "中国建筑史", 3, 1, 2, "前工院-204", "刘老师", "1-16", "读书报告", "green")],
            "4": [course("chen-visual", "VIS205", "视觉表达", 4, 6, 8, "美术教室", "孙老师", "2-14", "模型材料", "rose")],
            "5": [course("chen-urban", "URB202", "城市设计导论", 5, 3, 4, "四牌楼-东南院", "郑老师", "1-16", "案例分析展示", "amber")],
            "6": [],
            "7": [],
        },
        "plans": [
            ("设计竞赛概念草图", "竞赛", "2026-06-07 14:00", "2026-06-09 22:00", "2026-06-09 19:30", "doing", 3, "完成3张概念草图和一句话主题。"),
            ("建筑史读书报告", "课程", "2026-06-10 09:00", "2026-06-11 23:00", "2026-06-11 20:00", "todo", 2, "整理参考文献、案例图片和800字观点。"),
            ("周五讲座报名", "讲座", "2026-06-12 08:00", "2026-06-12 12:00", "2026-06-12 08:30", "todo", 1, "关注建筑学院公众号报名链接。"),
            ("建筑设计中期评图", "课程", "2026-06-13 09:00", "2026-06-13 17:00", "2026-06-12 22:00", "todo", 1, "准备总平面、分析图、模型照片和汇报顺序。"),
            ("数字建模作业导出", "课程", "2026-06-08 18:00", "2026-06-10 23:30", "2026-06-10 21:30", "doing", 2, "导出Rhino模型、渲染两张视角图。"),
            ("作品集案例页排版", "项目", "2026-06-14 10:00", "2026-06-16 23:00", "2026-06-15 20:00", "todo", 3, "完成城市更新案例的A3版式。"),
            ("学生会活动场地申请", "事务", "2026-06-09 10:00", "2026-06-09 17:00", "2026-06-09 09:30", "todo", 2, "提交活动教室申请和物料清单。"),
        ],
        "notifications": [
            ("news", "建筑讲座与展览", "关键词：建筑学院、城市更新、展览、讲座、论坛、四牌楼。优先推送线下可参加活动。", "daily", None, None, ["09:00", "18:00"]),
            ("news", "设计竞赛机会", "关键词：设计竞赛、城市设计、乡村振兴、空间设计、作品征集。", "daily", None, None, ["12:10"]),
            ("fixed", "评图与作业提醒", "每天晚上提醒建筑设计、模型、图纸、读书报告等课程节点。", "daily", None, None, ["22:00"]),
            ("news", "学生组织事务", "关键词：学生会、志愿活动、场地申请、活动招募。", "weekly", 1, None, ["19:00"]),
        ],
    },
    "test_zhaoxinyi": {
        "uuid": "9b1a7c6e-6a11-4a65-a8ab-0f4b5f1c0003",
        "nickname": "赵心怡",
        "gender": "女",
        "birthday": "2007-08-22",
        "major": "生物医学工程",
        "enrollment_year": 2025,
        "interest": ["医学影像", "志愿服务", "创新创业", "英语学习", "图像处理", "医疗AI"],
        "profile": {
            "real_name": "赵心怡",
            "campus": "九龙湖",
            "college": "生物科学与医学工程学院",
            "grade": "大一",
            "goals": ["了解医学AI项目", "参加志愿服务", "准备英语竞赛", "寻找生医工科研入门机会"],
            "preferences": {
                "interests": ["医学影像", "志愿服务", "创新创业", "英语学习", "图像处理", "医疗AI"],
                "goals": ["科研", "志愿", "英语", "创新创业"],
                "campus": "九龙湖",
                "preferred_notice_types": ["医学AI讲座", "科研招募", "志愿服务", "英语竞赛"],
                "avoid": ["纯硬件维修通知", "研究生限定通知"],
                "response_style": "语气温和，但需要明确截止时间和推荐理由",
            },
            "personal_description": "生医工大一学生，想尽早了解医学AI、医学影像和图像处理相关机会，同时需要管理英语展示、志愿时长和创新创业项目。希望系统把适合低年级参加的科研讲座、招募和活动筛出来。",
            "assistant_persona": "温和、高效、按优先级排序。遇到机会类通知时解释为什么适合我。",
        },
        "schedule": {
            "1": [course("zhao-calculus", "MATH101", "高等数学B", 1, 3, 4, "教二-208", "林老师", "1-16", "周一课堂测验", "green")],
            "2": [
                course("zhao-bme", "BME101", "生物医学工程导论", 2, 1, 2, "医工楼-301", "何老师", "1-16", "案例阅读", "violet"),
                course("zhao-chem", "CHEM101", "普通化学", 2, 6, 7, "实验楼-202", "许老师", "1-14", "穿实验服", "amber"),
            ],
            "3": [course("zhao-phy", "PHY101", "大学物理", 3, 3, 4, "教三-102", "马老师", "1-16", "带计算器", "blue")],
            "4": [course("zhao-program", "BME120", "Python与数据处理", 4, 8, 9, "机房C-105", "赵老师", "2-15", "提交notebook", "teal")],
            "5": [
                course("zhao-eng", "ENG102", "大学英语", 5, 1, 2, "外语楼-110", "沈老师", "1-16", "presentation", "rose"),
                course("zhao-pe", "PE103", "健身训练", 5, 6, 7, "九龙湖体育馆", "钱老师", "1-12", "运动服", "orange"),
            ],
            "6": [],
            "7": [],
        },
        "plans": [
            ("医学AI讲座报名", "讲座", "2026-06-08 12:00", "2026-06-08 18:00", "2026-06-08 12:30", "todo", 2, "查看医工学院通知并报名，确认地点是否在九龙湖。"),
            ("英语演讲稿初稿", "课程", "2026-06-09 16:00", "2026-06-10 21:00", "2026-06-10 19:00", "doing", 2, "完成3分钟英文presentation初稿。"),
            ("志愿服务时长登记", "事务", "2026-06-13 09:00", "2026-06-13 17:00", "2026-06-13 10:00", "todo", 1, "上传活动截图和服务证明。"),
            ("Python数据处理作业", "作业", "2026-06-07 18:00", "2026-06-09 23:00", "2026-06-09 20:00", "todo", 2, "完成Pandas清洗和Matplotlib可视化。"),
            ("医学影像论文精读", "科研", "2026-06-10 14:00", "2026-06-12 22:00", "2026-06-11 21:00", "todo", 3, "阅读一篇医学图像分割综述，记录关键词。"),
            ("创新创业队友沟通", "竞赛", "2026-06-11 19:00", "2026-06-11 21:00", "2026-06-11 18:30", "todo", 3, "确认项目方向、分工和报名材料。"),
            ("普通化学实验预习", "课程", "2026-06-08 20:00", "2026-06-09 12:00", "2026-06-08 21:00", "todo", 2, "写预习报告，确认试剂安全注意事项。"),
        ],
        "notifications": [
            ("news", "医学AI与生医工科研", "关键词：医学影像、医疗AI、生物医学工程、图像处理、科研招募、本科生项目。", "daily", None, None, ["08:20", "20:30"]),
            ("news", "志愿服务与公益活动", "关键词：志愿服务、公益活动、服务时长、校青协、医学科普。", "weekly", 1, None, ["12:00"]),
            ("news", "英语竞赛与国际交流", "关键词：英语演讲、四六级、国际交流、暑校、英文展示。", "weekly", 4, None, ["18:20"]),
            ("fixed", "课程DDL提醒", "每天晚上提醒英语展示、实验预习、Python作业和近期课程任务。", "daily", None, None, ["21:30"]),
        ],
    },
}


def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        for account, data in USERS.items():
            uid = data["uuid"]
            mapped = cur.execute("SELECT user_id FROM user_account_map WHERE account = ?", (account,)).fetchone()
            if not mapped or mapped[0] != uid:
                raise RuntimeError(f"account mapping missing or changed: {account}")

            cur.execute("DELETE FROM plan_table WHERE user_id = ?", (uid,))
            cur.execute("DELETE FROM notification_table WHERE user_id = ?", (uid,))
            cur.execute(
                """
                UPDATE users_table
                SET nickname = ?, gender = ?, birthday = ?, school = ?, major = ?,
                    enrollment_year = ?, interest = ?, profile = ?, schedule = ?
                WHERE uuid = ?
                """,
                (
                    data["nickname"],
                    data["gender"],
                    data["birthday"],
                    "东南大学",
                    data["major"],
                    data["enrollment_year"],
                    json.dumps(data["interest"], ensure_ascii=False),
                    json.dumps(data["profile"], ensure_ascii=False),
                    json.dumps({"schedule": data["schedule"]}, ensure_ascii=False),
                    uid,
                ),
            )
            for row in data["plans"]:
                cur.execute(
                    """
                    INSERT INTO plan_table(
                        user_id, name, type, start_time, end_time, reminder_time,
                        status, importance, description, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uid, *row, now, now),
                )
            for typ, title, content, frequency, weekday, notify_date, times in data["notifications"]:
                cur.execute(
                    """
                    INSERT INTO notification_table(
                        user_id, type, title, content, frequency, weekday,
                        notify_date, notify_times, enabled, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uid, typ, title, content, frequency, weekday, notify_date, json.dumps(times, ensure_ascii=False), 1, now, now),
                )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print("enriched users:", ", ".join(USERS))


if __name__ == "__main__":
    main()
