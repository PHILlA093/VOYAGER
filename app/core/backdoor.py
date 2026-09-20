"""双层验证协议(开发者模式):locked -> layer1 -> unlocked(持久化)。

两种触发途径等效:
1. 对话途径:依次说出两段暗号(evaluate)
2. 设置页途径:在「设置 → 开发者模式」依次输入两段验证码(check_layer1 / check_layer2)
"""
import re
import unicodedata


def _normalize(text):
    """去空白与全部标点、统一大小写,用于暗号比对。"""
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text.lower()


class Backdoor:
    def __init__(self, config, memory):
        self.config = config
        self.memory = memory
        self.layer1 = _normalize(config.get("passphrases", "layer1", default=""))
        self.layer2 = _normalize(config.get("passphrases", "layer2", default=""))
        self._layer1_passed = False
        self.unlocked = memory.get_meta("backdoor_unlocked", "0") == "1"

    # ---------- 设置页途径(开发者模式) ----------

    def check_layer1(self, code):
        """第一层验证。成功返回 True。"""
        if self.unlocked:
            return True
        if self.layer1 and _normalize(code) == self.layer1:
            self._layer1_passed = True
            return True
        return False

    def check_layer2(self, code):
        """第二层验证:须先通过第一层。成功则解锁并持久化。"""
        if self.unlocked:
            return True
        if self._layer1_passed and self.layer2 and _normalize(code) == self.layer2:
            self.unlocked = True
            self.memory.set_meta("backdoor_unlocked", "1")
            return True
        return False

    def lock(self):
        """退出开发者模式。"""
        self.unlocked = False
        self._layer1_passed = False
        self.memory.set_meta("backdoor_unlocked", "0")

    # ---------- 对话途径 ----------

    def evaluate(self, user_text):
        """根据用户输入更新状态,返回:locked / layer1 / unlocked。"""
        if self.unlocked:
            return "unlocked"
        norm = _normalize(user_text)
        if self.layer1 and norm == self.layer1:
            self._layer1_passed = True
            return "layer1"
        if self._layer1_passed and self.layer2 and norm == self.layer2:
            self.unlocked = True
            self.memory.set_meta("backdoor_unlocked", "1")
            return "unlocked"
        return "layer1" if self._layer1_passed else "locked"
