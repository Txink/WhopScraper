"""
样本管理模块
用于收集、分类和管理消息样本，方便后续改进正则解析规则
"""
import json
import os
from datetime import datetime
from typing import Optional, List, Dict
from enum import Enum


class SampleCategory(Enum):
    """样本分类"""
    OPEN = "开仓指令"
    STOP_LOSS = "止损指令"
    TAKE_PROFIT = "止盈指令"
    ADJUST = "调整指令"
    UNKNOWN = "未识别"
    OTHER = "其他"


class Sample:
    """消息样本"""
    
    def __init__(
        self,
        message: str,
        category: str = SampleCategory.UNKNOWN.value,
        notes: str = "",
        parsed_successfully: bool = False,
        parsed_result: Optional[Dict] = None,
        timestamp: Optional[str] = None
    ):
        self.message = message
        self.category = category
        self.notes = notes
        self.parsed_successfully = parsed_successfully
        self.parsed_result = parsed_result or {}
        self.timestamp = timestamp or datetime.now().isoformat()
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "message": self.message,
            "category": self.category,
            "notes": self.notes,
            "parsed_successfully": self.parsed_successfully,
            "parsed_result": self.parsed_result,
            "timestamp": self.timestamp
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Sample":
        """从字典创建样本"""
        return cls(
            message=data.get("message", ""),
            category=data.get("category", SampleCategory.UNKNOWN.value),
            notes=data.get("notes", ""),
            parsed_successfully=data.get("parsed_successfully", False),
            parsed_result=data.get("parsed_result"),
            timestamp=data.get("timestamp")
        )


class SampleManager:
    """样本管理器"""
    
    def __init__(self, samples_file: str = "samples/samples.json"):
        """
        初始化样本管理器
        
        Args:
            samples_file: 样本存储文件路径
        """
        self.samples_file = samples_file
        self.samples: List[Sample] = []
        self._load()
    
    def _load(self):
        """从文件加载样本"""
        if os.path.exists(self.samples_file):
            try:
                with open(self.samples_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.samples = [Sample.from_dict(item) for item in data]
                print(f"已加载 {len(self.samples)} 个样本")
            except (json.JSONDecodeError, IOError) as e:
                print(f"加载样本文件失败: {e}")
                self.samples = []
        else:
            print(f"样本文件不存在，将创建新文件: {self.samples_file}")
            self.samples = []
    
    def _save(self):
        """保存样本到文件"""
        os.makedirs(os.path.dirname(self.samples_file) or ".", exist_ok=True)
        
        with open(self.samples_file, "w", encoding="utf-8") as f:
            json.dump(
                [s.to_dict() for s in self.samples],
                f,
                ensure_ascii=False,
                indent=2
            )
    
    def add_sample(
        self,
        message: str,
        category: str = SampleCategory.UNKNOWN.value,
        notes: str = "",
        parsed_successfully: bool = False,
        parsed_result: Optional[Dict] = None
    ) -> Sample:
        """
        添加新样本
        
        Args:
            message: 消息内容
            category: 分类
            notes: 备注
            parsed_successfully: 是否成功解析
            parsed_result: 解析结果
            
        Returns:
            创建的样本对象
        """
        # 检查是否已存在相同消息
        for existing in self.samples:
            if existing.message == message:
                print(f"样本已存在: {message[:50]}...")
                return existing
        
        sample = Sample(
            message=message,
            category=category,
            notes=notes,
            parsed_successfully=parsed_successfully,
            parsed_result=parsed_result
        )
        
        self.samples.append(sample)
        self._save()
        
        print(f"已添加样本 [{category}]: {message[:50]}...")
        return sample
    
    def add_unparsed_sample(self, message: str, notes: str = ""):
        """
        添加未能解析的样本
        
        Args:
            message: 消息内容
            notes: 备注
        """
        return self.add_sample(
            message=message,
            category=SampleCategory.UNKNOWN.value,
            notes=notes,
            parsed_successfully=False
        )
    
    def add_parsed_sample(
        self,
        message: str,
        category: str,
        parsed_result: Dict,
        notes: str = ""
    ):
        """
        添加成功解析的样本
        
        Args:
            message: 消息内容
            category: 分类
            parsed_result: 解析结果
            notes: 备注
        """
        return self.add_sample(
            message=message,
            category=category,
            notes=notes,
            parsed_successfully=True,
            parsed_result=parsed_result
        )
    
    def get_samples_by_category(self, category: str) -> List[Sample]:
        """
        按分类获取样本
        
        Args:
            category: 分类
            
        Returns:
            样本列表
        """
        return [s for s in self.samples if s.category == category]
    
    def get_unparsed_samples(self) -> List[Sample]:
        """获取所有未成功解析的样本"""
        return [s for s in self.samples if not s.parsed_successfully]
    
    def get_parsed_samples(self) -> List[Sample]:
        """获取所有成功解析的样本"""
        return [s for s in self.samples if s.parsed_successfully]
    
    def update_sample(
        self,
        message: str,
        category: Optional[str] = None,
        notes: Optional[str] = None,
        parsed_successfully: Optional[bool] = None,
        parsed_result: Optional[Dict] = None
    ) -> bool:
        """
        更新样本
        
        Args:
            message: 要更新的消息（用于查找样本）
            category: 新分类
            notes: 新备注
            parsed_successfully: 是否成功解析
            parsed_result: 解析结果
            
        Returns:
            是否更新成功
        """
        for sample in self.samples:
            if sample.message == message:
                if category is not None:
                    sample.category = category
                if notes is not None:
                    sample.notes = notes
                if parsed_successfully is not None:
                    sample.parsed_successfully = parsed_successfully
                if parsed_result is not None:
                    sample.parsed_result = parsed_result
                
                self._save()
                print(f"已更新样本: {message[:50]}...")
                return True
        
        print(f"找不到样本: {message[:50]}...")
        return False
    
    def remove_sample(self, message: str) -> bool:
        """
        删除样本
        
        Args:
            message: 要删除的消息
            
        Returns:
            是否删除成功
        """
        for i, sample in enumerate(self.samples):
            if sample.message == message:
                del self.samples[i]
                self._save()
                print(f"已删除样本: {message[:50]}...")
                return True
        
        print(f"找不到样本: {message[:50]}...")
        return False
    
    def export_by_category(self, category: str, output_file: str):
        """
        按分类导出样本
        
        Args:
            category: 分类
            output_file: 输出文件路径
        """
        samples = self.get_samples_by_category(category)
        
        with open(output_file, "w", encoding="utf-8") as f:
            for sample in samples:
                f.write(f"{sample.message}\n")
                if sample.notes:
                    f.write(f"  # {sample.notes}\n")
                if sample.parsed_result:
                    f.write(f"  # 解析结果: {sample.parsed_result}\n")
                f.write("\n")
        
        print(f"已导出 {len(samples)} 个 [{category}] 样本到: {output_file}")
    
    def generate_report(self) -> str:
        """
        生成样本统计报告
        
        Returns:
            报告文本
        """
        total = len(self.samples)
        parsed = len(self.get_parsed_samples())
        unparsed = len(self.get_unparsed_samples())
        
        report = f"""
样本统计报告
{'=' * 60}
总样本数: {total}
成功解析: {parsed} ({parsed/total*100:.1f}% if total > 0 else 0)
未能解析: {unparsed} ({unparsed/total*100:.1f}% if total > 0 else 0)

按分类统计:
"""
        
        for category in SampleCategory:
            count = len(self.get_samples_by_category(category.value))
            if count > 0:
                report += f"  - {category.value}: {count}\n"
        
        report += "=" * 60
        return report
    
    def list_samples(
        self,
        category: Optional[str] = None,
        limit: int = 10,
        unparsed_only: bool = False
    ):
        """
        列出样本
        
        Args:
            category: 分类过滤
            limit: 显示数量限制
            unparsed_only: 仅显示未解析的样本
        """
        samples = self.samples
        
        if category:
            samples = [s for s in samples if s.category == category]
        
        if unparsed_only:
            samples = [s for s in samples if not s.parsed_successfully]
        
        print(f"\n样本列表 (显示前 {limit} 个):")
        print("=" * 60)
        
        for i, sample in enumerate(samples[:limit]):
            status = "✓" if sample.parsed_successfully else "✗"
            print(f"\n[{i+1}] {status} [{sample.category}]")
            print(f"消息: {sample.message}")
            if sample.notes:
                print(f"备注: {sample.notes}")
            if sample.parsed_result:
                print(f"解析: {sample.parsed_result}")
            print(f"时间: {sample.timestamp}")
        
        if len(samples) > limit:
            print(f"\n... 还有 {len(samples) - limit} 个样本")
        
        print("=" * 60)


# 命令行工具
if __name__ == "__main__":
    import sys
    
    manager = SampleManager()
    
    if len(sys.argv) < 2:
        print("用法:")
        print("  python sample_manager.py list [category] [--unparsed]")
        print("  python sample_manager.py report")
        print("  python sample_manager.py add <message> [category] [notes]")
        print("  python sample_manager.py export <category> <output_file>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        category = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
        unparsed_only = "--unparsed" in sys.argv
        manager.list_samples(category=category, unparsed_only=unparsed_only, limit=20)
    
    elif command == "report":
        print(manager.generate_report())
    
    elif command == "add":
        if len(sys.argv) < 3:
            print("错误: 请提供消息内容")
            sys.exit(1)
        message = sys.argv[2]
        category = sys.argv[3] if len(sys.argv) > 3 else SampleCategory.UNKNOWN.value
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
        manager.add_sample(message, category, notes)
    
    elif command == "export":
        if len(sys.argv) < 4:
            print("错误: 请提供分类和输出文件")
            sys.exit(1)
        category = sys.argv[2]
        output_file = sys.argv[3]
        manager.export_by_category(category, output_file)
    
    else:
        print(f"未知命令: {command}")
