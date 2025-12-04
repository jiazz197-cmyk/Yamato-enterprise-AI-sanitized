"""
测试 Retriever API 端点
运行方式: python test_retriever.py
"""
import requests
import json
from typing import Optional


class RetrieverTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.api_prefix = "/api/v1/retriever"
    
    def test_health_check(self):
        """测试健康检查"""
        print("\n" + "="*50)
        print("测试 1: 健康检查")
        print("="*50)
        
        try:
            response = requests.get(f"{self.base_url}/health")
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    def test_rag_status(self):
        """测试 RAG 系统状态"""
        print("\n" + "="*50)
        print("测试 2: RAG 系统状态")
        print("="*50)
        
        try:
            response = requests.get(f"{self.base_url}/test/rag-status")
            print(f"状态码: {response.status_code}")
            result = response.json()
            print(f"RAG 状态: {result['status']}")
            print(f"消息: {result['message']}")
            return result['status'] == 'initialized'
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    def test_db_endpoint(self, question: str, collection_name: Optional[str] = None):
        """测试 /db 端点 - 数据库检索"""
        print("\n" + "="*50)
        print("测试 3: /db 端点 - 数据库检索")
        print("="*50)
        
        url = f"{self.base_url}{self.api_prefix}/db"
        payload = {
            "question": question,
            "collection_name": collection_name
        }
        
        print(f"请求 URL: {url}")
        print(f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        try:
            response = requests.post(url, json=payload)
            print(f"\n状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ 成功! 返回结果:")
                print(f"  - 内容条数: {len(result.get('content', []))}")
                print(f"  - 来源条数: {len(result.get('source', []))}")
                if result.get('content'):
                    print(f"  - 第一条内容预览: {result['content'][0][:100]}...")
                return True
            else:
                print(f"❌ 失败: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    def test_excel_endpoint(self, question: str, collection_name: Optional[str] = None):
        """测试 /excel 端点 - Excel 文件检索与转换"""
        print("\n" + "="*50)
        print("测试 4: /excel 端点 - Excel 检索")
        print("="*50)
        
        url = f"{self.base_url}{self.api_prefix}/excel"
        payload = {
            "question": question,
            "collection_name": collection_name
        }
        
        print(f"请求 URL: {url}")
        print(f"请求数据: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        
        try:
            response = requests.post(url, json=payload)
            print(f"\n状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ 成功! 返回结果:")
                
                if isinstance(result, dict):
                    if 'error' in result:
                        print(f"  - 错误信息: {result['error']}")
                    elif 'data' in result:
                        print(f"  - 数据行数: {len(result.get('data', []))}")
                    else:
                        print(f"  - 返回键: {list(result.keys())}")
                else:
                    print(f"  - 返回类型: {type(result)}")
                
                return True
            else:
                print(f"❌ 失败: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    def test_charts_endpoint(self, data_source: dict, requirements: dict):
        """测试 /charts 端点 - 图表生成"""
        print("\n" + "="*50)
        print("测试 5: /charts 端点 - 图表生成")
        print("="*50)
        
        url = f"{self.base_url}{self.api_prefix}/charts"
        payload = {
            "data_source": data_source,
            "requirements": requirements
        }
        
        print(f"请求 URL: {url}")
        print(f"请求数据预览: data_source 类型: {type(data_source)}, requirements: {requirements}")
        
        try:
            response = requests.post(url, json=payload)
            print(f"\n状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ 成功! 返回结果:")
                
                if isinstance(result, list):
                    print(f"  - 图表数量: {len(result)}")
                    for i, chart in enumerate(result[:3]):  # 只显示前3个
                        print(f"  - 图表 {i+1}: {chart.get('title', 'N/A')}")
                elif isinstance(result, dict):
                    print(f"  - 返回键: {list(result.keys())}")
                
                return True
            else:
                print(f"❌ 失败: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ 错误: {e}")
            return False
    
    def run_all_tests(self):
        """运行所有测试"""
        print("\n" + "="*60)
        print(" Retriever API 测试套件")
        print("="*60)
        
        results = []
        
        # 基础测试
        results.append(("健康检查", self.test_health_check()))
        results.append(("RAG状态检查", self.test_rag_status()))
        
        # Retriever 端点测试
        results.append((
            "/db 端点",
            self.test_db_endpoint(
                question="什么是机器学习?",
                collection_name="doc_collection_1"
            )
        ))
        
        results.append((
            "/excel 端点",
            self.test_excel_endpoint(
                question="销售数据",
                collection_name="doc_collection_1"
            )
        ))
        
        # Charts 端点测试 - 使用示例数据
        sample_data = {
            "data": [
                {"date": "2024-01", "value": 100},
                {"date": "2024-02", "value": 150},
                {"date": "2024-03", "value": 120}
            ]
        }
        sample_requirements = {
            "chart_type": "line"
        }
        
        results.append((
            "/charts 端点",
            self.test_charts_endpoint(sample_data, sample_requirements)
        ))
        
        # 输出测试总结
        print("\n" + "="*60)
        print(" 测试总结")
        print("="*60)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ 通过" if result else "❌ 失败"
            print(f"{status} - {test_name}")
        
        print(f"\n总计: {passed}/{total} 测试通过")
        
        return passed == total


def main():
    """主函数"""
    import sys
    
    # 检查是否提供了自定义 URL
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    
    print(f"使用基础 URL: {base_url}")
    print("请确保服务已经启动！")
    print("可以通过运行 'python main.py' 来启动服务")
    
    input("\n按 Enter 键开始测试...")
    
    tester = RetrieverTester(base_url=base_url)
    success = tester.run_all_tests()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

