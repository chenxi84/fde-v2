"""FDE 平台 SDK —— 平台提供给所有 FDE 应用的公共依赖（见 CONVENTION.md §4 / §7）。

应用文件通过 `from fde import FdeError` 引用本模块。运行期，平台还会向每个聚合根
实例注入三个属性：
    self.ctx  身份上下文 {userno, departmentno, role}（平台权威、跨应用自动透传）
    self.db   指向同名 .db 的 SQLite 连接（已开 WAL / busy_timeout / 行工厂；事务归平台）
    self.fde  跨应用网关，提供 self.fde.call("应用名", "服务名", **参数)

本模块随平台实现逐步补齐；目前仅含业务异常基类 FdeError。

Author: chenxi <tomcx@qq.com>
"""


class FdeError(Exception):
    """业务失败异常。

    聚合根方法用它表示一次「干净的业务错误」（如"用户不存在""部门编号已存在"）：
      - 平台将其归一为带可读信息的业务失败，而不是系统错误；
      - 跨应用调用 self.fde.call 会把它原样传播给调用方，调用方可 try/except 捕获。
    与之相对，未预期的程序异常视为系统错误，由平台另行记录并对调用方屏蔽细节。
    """
