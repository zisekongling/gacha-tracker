from flask import Flask, jsonify
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
import time
import argparse

# 通用配置
MAX_VERSIONS = 10

app = Flask(__name__)
app.config['JSON_SORT_KEYS'] = False

# ==================== 原神卡池数据 ====================

def parse_genshin_gacha_table(table):
    """解析单个原神卡池表格"""
    try:
        # 提取卡池名称
        header = table.find('th', colspan="2")
        name = "未知卡池"
        if header:
            name_img = header.find('img')
            if name_img and name_img.get('alt'):
                name = name_img['alt']
            else:
                name_text = header.get_text(strip=True)
                if name_text:
                    name = name_text
        
        # 确定卡池类型
        pool_type = "角色池"
        if "武器" in name or "神铸赋形" in name:
            pool_type = "武器池"
        elif "集录" in name:
            pool_type = "混池（集录）"
        
        # 查找所有行
        rows = table.find_all('tr')
        data = {
            "name": name,
            "type": pool_type,
            "version": "",
            "version_key": "其他",
            "start_time": "",
            "end_time": "",
            "five_stars": [],
            "four_stars": []
        }
        
        # 处理所有行
        for row in rows:
            th = row.find('th')
            if not th:
                continue
                
            header_text = th.get_text(strip=True)
            td = row.find('td')
            if not td:
                continue
            
            # 处理时间
            if "时间" in header_text or "期間" in header_text:
                date_str = td.get_text(strip=True)
                if "~" in date_str:
                    parts = date_str.split('~', 1)
                    if len(parts) == 2:
                        data["start_time"] = parts[0].strip()
                        data["end_time"] = parts[1].strip()
                elif "至" in date_str:
                    parts = date_str.split('至', 1)
                    if len(parts) == 2:
                        data["start_time"] = parts[0].strip()
                        data["end_time"] = parts[1].strip()
            
            # 处理版本
            elif "版本" in header_text:
                data["version"] = td.get_text(strip=True)
                # 提取版本号
                version_match = re.search(r'(\d+\.\d+|[月之]\S+)(上半|下半)?', data["version"])
                if version_match:
                    data["version_key"] = version_match.group(1)
            
            # 处理五星内容
            elif "5星" in header_text or "五星" in header_text or "5星角色" in header_text or "5星武器" in header_text:
                data["five_stars"] = [a.get_text(strip=True) for a in td.find_all('a') if a.get_text(strip=True)]
            
            # 处理四星内容
            elif "4星" in header_text or "四星" in header_text or "4星角色" in header_text or "4星武器" in header_text:
                data["four_stars"] = [a.get_text(strip=True) for a in td.find_all('a') if a.get_text(strip=True)]
        
        return data
    except Exception as e:
        print(f"解析原神表格时出错: {e}")
        return None

def fetch_genshin_gacha_data():
    """获取原神祈愿数据"""
    try:
        print("开始从biligame获取原神祈愿数据...")
        
        # 解析往期祈愿和集录祈愿页面
        print("获取往期祈愿页面...")
        response1 = requests.get("https://wiki.biligame.com/ys/往期祈愿", timeout=30)
        response1.raise_for_status()
        soup1 = BeautifulSoup(response1.content, 'html.parser')
        
        print("获取集录祈愿页面...")
        response2 = requests.get("https://wiki.biligame.com/ys/集录祈愿", timeout=30)
        response2.raise_for_status()
        soup2 = BeautifulSoup(response2.content, 'html.parser')
        
        all_gacha_data = []
        seen_names = set()
        current_year = datetime.now().year
        
        # 修改点：正确提取嵌套表格
        tables = []
        
        # 处理往期祈愿页面：查找所有包含卡池的内部表格
        for outer_table in soup1.find_all('table', class_='wikitable'):
            # 在内层查找所有卡池表格
            inner_tables = outer_table.find_all('table', class_='ys-qy-table')
            tables.extend(inner_tables)
        
        # 处理集录祈愿页面：直接获取所有表格
        tables.extend(soup2.find_all('table', class_='wikitable'))
        
        print(f"发现有效卡池表格: {len(tables)} 个")
        
        # 解析所有卡池表格
        successful_parses = 0
        for i, table in enumerate(tables, 1):
            try:
                print(f"解析表格 {i}/{len(tables)}...")
                entry = parse_genshin_gacha_table(table)
                if not entry or not entry.get("name") or entry["name"] == "未知卡池":
                    print(f"表格 {i} 未找到有效名称，跳过")
                    continue
                    
                if entry["name"] in seen_names:
                    print(f"跳过重复卡池: {entry['name']}")
                    continue
                    
                # 添加年份到日期（如果日期中还没有年份）
                if entry["start_time"] and not re.search(r'\d{4}', entry["start_time"]):
                    entry["start_time"] = f"{current_year}/" + entry["start_time"].replace('/', '-')
                if entry["end_time"] and not re.search(r'\d{4}', entry["end_time"]):
                    entry["end_time"] = f"{current_year}/" + entry["end_time"].replace('/', '-')
                
                print(f"添加卡池: {entry['name']} ({entry['type']}) - 五星: {len(entry['five_stars'])}个, 四星: {len(entry['four_stars'])}个")
                all_gacha_data.append(entry)
                seen_names.add(entry["name"])
                successful_parses += 1
                
            except Exception as e:
                print(f"解析表格 {i} 出错: {e}")
                continue

        print(f"成功解析卡池数: {successful_parses}")
        
        if successful_parses == 0:
            return {"error": "未能成功解析任何卡池数据"}
        
        # 按版本分组
        version_data = {}
        for entry in all_gacha_data:
            key = entry.get("version_key", "其他")
            if not key or key == "其他":
                # 尝试从名称中提取版本信息
                name = entry["name"]
                if "089" in name:
                    key = "月之一"
                elif "088" in name:
                    key = "月之一"
                elif "087" in name:
                    key = "5.8"
                elif "086" in name:
                    key = "5.8"
                elif "085" in name:
                    key = "5.7"
                elif "084" in name:
                    key = "5.7"
                elif "083" in name:
                    key = "5.6"
                elif "082" in name:
                    key = "5.6"
                elif "081" in name:
                    key = "5.5"
                elif "080" in name:
                    key = "5.5"
                elif "079" in name:
                    key = "5.4"
                elif "078" in name:
                    key = "5.4"
                elif "077" in name:
                    key = "5.3"
                elif "076" in name:
                    key = "5.3"
                elif "075" in name:
                    key = "5.2"
                elif "074" in name:
                    key = "5.2"
                else:
                    key = "其他"
            
            version_data.setdefault(key, []).append(entry)
        
        # 获取最新版本
        def version_sort_key(v):
            if v == "其他":
                return [0, 0]
            elif v.startswith("月之"):
                try:
                    # 月之版本排在前面，数字越大越新
                    version_num = int(v.replace("月之", ""))
                    return [999, version_num]
                except:
                    return [999, 0]
            else:
                try:
                    return [int(part) for part in v.split('.')]
                except:
                    return [0, 0]
        
        sorted_versions = sorted(
            version_data.keys(), 
            key=version_sort_key, 
            reverse=True
        )
        
        # 只取最新的版本
        latest_versions = sorted_versions[:MAX_VERSIONS]
        print(f"所有版本: {sorted_versions}")
        print(f"最新版本: {latest_versions}")
        
        # 构建最终数据结构
        result = {
            "last_updated": datetime.now().isoformat(),
            "total_pools": successful_parses,
            "latest_versions": latest_versions,
            "gacha_data": []
        }
        
        # 只包含最新版本的数据
        for version in latest_versions:
            result["gacha_data"].extend(version_data[version])
        
        print(f"最终返回卡池数: {len(result['gacha_data'])}")
        return result
    
    except requests.RequestException as e:
        print(f"网络请求出错: {e}")
        return {"error": f"网络请求失败: {str(e)}"}
    except Exception as e:
        print(f"获取祈愿数据出错: {e}")
        import traceback
        traceback.print_exc()
        return {"error": f"无法获取祈愿数据: {str(e)}"}

# ==================== 星穹铁道卡池数据 ====================

def parse_star_rail_time_range(time_str):
    """解析星穹铁道时间范围字符串"""
    # 清理字符串：去除多余空格和换行
    time_str = re.sub(r'\s+', ' ', time_str).strip()
    
    # 尝试匹配日期格式：YYYY/MM/DD HH:MM
    date_pattern = r'\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}'
    
    # 查找所有匹配的日期
    dates = re.findall(date_pattern, time_str)
    
    # 如果有两个日期，则第一个是开始时间，第二个是结束时间
    if len(dates) == 2:
        return dates[0], dates[1]
    
    # 如果只有一个日期，则作为结束时间
    elif len(dates) == 1:
        # 检查是否有版本更新后的描述
        if '版本更新后' in time_str:
            version_match = re.search(r'(\d+\.\d+)', time_str)
            version = version_match.group(1) if version_match else "未知版本"
            return f"{version}版本更新后", dates[0]
        else:
            return "", dates[0]
    
    # 如果没有日期，尝试其他格式
    else:
        # 尝试按分隔符分割
        separators = ['~', '-', '至']
        for sep in separators:
            if sep in time_str:
                parts = time_str.split(sep, 1)
                if len(parts) == 2:
                    return parts[0].strip(), parts[1].strip()
        
        # 如果都没有匹配，返回原始字符串
        return time_str, ""

def scrape_hsr_wish_data():
    """从biligame维基爬取崩坏：星穹铁道卡池信息"""
    url = "https://wiki.biligame.com/sr/%E5%8E%86%E5%8F%B2%E8%B7%83%E8%BF%81"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 定位包含版本信息的容器
        wish_data = []
        version_containers = []
        
        # 查找所有版本标题（h4标签）
        version_headers = soup.find_all(['h3', 'h4'], class_=lambda x: x != 'mw-editsection')
        
        # 收集最近版本的容器
        for header in version_headers:
            if header.find('span', class_='mw-headline'):
                version_containers.append(header)
                if len(version_containers) >= MAX_VERSIONS:  # 只取最近版本
                    break
        
        # 遍历每个版本容器
        for container in version_containers:
            # 找到当前容器下所有卡池表格
            wish_tables = []
            next_sibling = container.next_sibling
            
            # 收集直到下一个标题的所有表格
            while next_sibling and next_sibling.name not in ['h3', 'h4']:
                if next_sibling.name == 'div' and 'row' in next_sibling.get('class', []):
                    wish_tables.extend(next_sibling.find_all('table', class_='wikitable'))
                next_sibling = next_sibling.next_sibling
            
            # 处理每个卡池表格
            for table in wish_tables:
                wish_info = {}
                
                # 提取时间
                time_th = table.find('th', string='时间')
                if not time_th:
                    time_th = table.find('th', string=re.compile(r'时间'))
                if time_th:
                    time_td = time_th.find_next('td')
                    if time_td:
                        wish_info['时间'] = time_td.get_text(strip=False).replace('\t', '')
                
                # 提取版本
                version_th = table.find('th', string='版本')
                if not version_th:
                    version_th = table.find('th', string=re.compile(r'版本'))
                if version_th:
                    version_td = version_th.find_next('td')
                    if version_td:
                        version_text = version_td.get_text(strip=True)
                        version_match = re.search(r'(\d+\.\d+)', version_text)
                        if version_match:
                            wish_info['版本'] = version_match.group(1)
                        else:
                            wish_info['版本'] = version_text
                
                # 提取5星角色/光锥 - 保留完整文本
                star5_row = table.find('th', string=re.compile(r'5星(角色|光锥)'))
                if star5_row:
                    star5_type = "角色" if "角色" in star5_row.get_text() else "光锥"
                    star5_td = star5_row.find_next('td')
                    if star5_td:
                        star5_text = star5_td.get_text(strip=True)
                        star5_text = re.sub(r'\s+', ' ', star5_text)
                        wish_info['5星类型'] = star5_type
                        wish_info['5星内容'] = star5_text
                
                # 提取4星角色/光锥
                star4_row = table.find('th', string=re.compile(r'4星(角色|光锥)'))
                if star4_row:
                    star4_type = "角色" if "角色" in star4_row.get_text() else "光锥"
                    star4_td = star4_row.find_next('td')
                    if star4_td:
                        star4_items = []
                        for item in star4_td.children:
                            if item.name == 'br':
                                continue
                            if item.name == 'a':
                                item_text = item.get_text(strip=True)
                                if item_text:
                                    star4_items.append(item_text)
                            elif isinstance(item, str) and item.strip():
                                star4_items.append(item.strip())
                        
                        if not star4_items:
                            star4_text = star4_td.get_text(strip=True)
                            star4_items = [s.strip() for s in star4_text.split('\n') if s.strip()]
                        
                        wish_info['4星类型'] = star4_type
                        wish_info['4星内容'] = ", ".join(star4_items)
                
                # 确定卡池类型
                if '5星类型' in wish_info:
                    wish_info['卡池类型'] = "角色池" if wish_info['5星类型'] == "角色" else "光锥池"
                    wish_data.append(wish_info)
        
        return wish_data
    
    except Exception as e:
        print(f"爬取星穹铁道卡池数据时出错: {str(e)}")
        return []

def format_hsr_wish_data(wish_data):
    """格式化星穹铁道卡池数据用于API输出"""
    formatted_data = []
    
    for wish in wish_data:
        # 提取卡池版本
        version = wish.get('版本', '未知版本')
        
        # 解析时间范围
        time_str = wish.get('时间', '时间未知')
        start_time, end_time = parse_star_rail_time_range(time_str)
        
        # 保留完整的5星内容（包括属性信息）
        star5_content = wish.get('5星内容', '未知')
        
        formatted_data.append({
            "version": version,
            "pool_type": wish.get('卡池类型', '未知'),
            "start_time": start_time,
            "end_time": end_time,
            "five_star": star5_content,
            "four_star": wish.get('4星内容', '')
        })
    
    return formatted_data

def fetch_hsr_wish_data():
    raw_data = scrape_hsr_wish_data()
    if not raw_data:
        return {"error": "Failed to fetch wish data"}
        
    formatted_data = format_hsr_wish_data(raw_data)
    
    if not formatted_data:
        return {"error": "No valid wish data found"}
        
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    response = {
        "last_updated": current_time,
        "wish_data": formatted_data
    }
    
    return response

# ==================== 绝区零卡池数据 ====================

def extract_zzz_agent_data(td):
    """提取绝区零代理人数据"""
    # 尝试提取链接
    agents = []
    for a in td.find_all('a'):
        agent_text = a.get_text(strip=True)
        if agent_text:
            agents.append(agent_text)
    
    # 如果没有链接，处理纯文本
    if not agents:
        text_content = td.get_text(strip=True)
        # 使用正则表达式提取方括号内的内容
        matches = re.findall(r'\[([^\]]+)\]', text_content)
        if matches:
            agents = matches
        elif text_content:
            # 尝试按换行分割
            lines = [line.strip() for line in text_content.split('\n') if line.strip()]
            if lines:
                agents = lines
            else:
                agents = [text_content]
    
    return agents

def extract_zzz_pool_data(table, pool_type):
    """从单个绝区零卡池表格中提取数据"""
    data = {"type": pool_type}
    
    # 提取卡池名称 - 处理不同情况
    title_th = table.find('th', class_='ys-qy-title')
    if title_th:
        # 尝试提取链接文本
        a_tag = title_th.find('a')
        if a_tag:
            if a_tag.get('title'):
                data['name'] = a_tag['title'].replace('文件:', '').replace('.png', '').strip()
            else:
                data['name'] = a_tag.get_text(strip=True)
        
        # 尝试提取图片文本
        img_tag = title_th.find('img')
        if img_tag and not data.get('name'):
            if img_tag.get('alt'):
                data['name'] = img_tag['alt'].strip()
            elif img_tag.get('title'):
                data['name'] = img_tag['title'].strip()
    
    # 如果以上方法都失败，直接提取th文本
    if not data.get('name') and title_th:
        data['name'] = title_th.get_text(strip=True)
    
    # 提取所有行
    rows = table.find_all('tr')
    agent_headers = []  # 记录表头信息用于类型判断
    
    for row in rows:
        th = row.find('th')
        td = row.find('td')
        if not th or not td:
            continue
            
        header = th.get_text(strip=True)
        agent_headers.append(header)  # 收集表头信息
        
        # 统一处理S级/A级数据
        if header in ['S级代理人', 'S级音擎']:
            data['up_s'] = extract_zzz_agent_data(td)
        elif header in ['A级代理人', 'A级音擎']:
            data['up_a'] = extract_zzz_agent_data(td)
        elif header == '时间':
            data['time'] = td.get_text(strip=True)
        elif header == '版本':
            data['version'] = td.get_text(strip=True)
    
    # 优化卡池类型判断逻辑
    # 方法1: 检查表头特征词
    if any("代理人" in h for h in agent_headers):
        data['type'] = "character"
    elif any("音擎" in h for h in agent_headers):
        data['type'] = "weapon"
    # 方法2: 检查卡池名称特征词
    elif 'name' in data:
        if "角色" in data['name'] or "代理人" in data['name']:
            data['type'] = "character"
        elif "音擎" in data['name'] or "武器" in data['name']:
            data['type'] = "weapon"
    # 方法3: 检查UP物品数量特征
    elif len(data.get('up_s', [])) > 1:  # 角色池通常只有一个S级UP
        data['type'] = "weapon"
    
    return data

def get_zzz_gacha_data():
    """获取绝区零卡池数据"""
    url = "https://wiki.biligame.com/zzz/%E5%BE%80%E6%9C%9F%E8%B0%83%E9%A2%91"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        return {"error": f"请求失败: {str(e)}"}
    
    soup = BeautifulSoup(response.content, 'html.parser')
    all_versions = []
    
    # 找到所有版本标题 (h3标签)
    version_headings = soup.find_all('h3')
    for heading in version_headings:
        version_span = heading.find('span', class_='mw-headline')
        if not version_span:
            continue
            
        version_title = version_span.get_text(strip=True)
        if '·' in version_title:
            version_number = version_title.split('·')[0].strip()
            # 判断是上半还是下半
            if "第一" in version_title or "上半" in version_title:
                phase = "上半"
            elif "第二" in version_title or "下半" in version_title:
                phase = "下半"
            else:
                phase = "未知"
        else:
            continue
        
        # 获取当前版本区块的所有外层表格
        version_tables = []
        next_element = heading.find_next_sibling()
        while next_element and next_element.name != 'h3':
            # 查找所有wikitable表格（外层表格）
            if next_element.name == 'table' and 'wikitable' in next_element.get('class', []):
                version_tables.append(next_element)
            next_element = next_element.find_next_sibling()
        
        pools = []
        for outer_table in version_tables:
            # 查找所有内嵌的卡池表格
            inner_tables = outer_table.find_all('table', class_='wikitable')
            for inner_table in inner_tables:
                # 检查是否是卡池表格（包含ys-qy-title类）
                if inner_table.find('th', class_='ys-qy-title'):
                    # 初始类型判断（后续会优化）
                    pool_type = "character" if "独家频段" in inner_table.get_text() else "weapon" if "音擎频段" in inner_table.get_text() else "unknown"
                    pools.append(extract_zzz_pool_data(inner_table, pool_type))
        
        if pools:
            all_versions.append({
                "version": version_number,
                "phase": phase,
                "pools": pools
            })
    
    # 按版本号排序（从新到旧）
    all_versions.sort(
        key=lambda x: [int(part) for part in x['version'].split('.')],
        reverse=True
    )
    
    # 只保留最新的版本
    latest_versions = all_versions[:MAX_VERSIONS]
    
    return latest_versions

# ==================== API接口 ====================

@app.route('/api/genshin', methods=['GET'])
def get_genshin_data():
    """API端点，返回原神卡池信息"""
    result = fetch_genshin_gacha_data()
    if isinstance(result, dict) and 'error' in result:
        return jsonify({"error": result['error']}), 500
    return jsonify(result)

@app.route('/api/hsr', methods=['GET'])
def get_hsr_data():
    """API端点，返回星穹铁道卡池信息"""
    result = fetch_hsr_wish_data()
    if isinstance(result, dict) and 'error' in result:
        return jsonify({"error": result['error']}), 500
    return jsonify(result)

@app.route('/api/zzz', methods=['GET'])
def get_zzz_data():
    """API端点，返回绝区零卡池信息"""
    result = get_zzz_gacha_data()
    if isinstance(result, dict) and 'error' in result:
        return jsonify({"error": result['error']}), 500
    return jsonify(result)

@app.route('/api/all', methods=['GET'])
def get_all_data():
    """API端点，返回所有游戏的卡池信息"""
    genshin_data = fetch_genshin_gacha_data()
    hsr_data = fetch_hsr_wish_data()
    zzz_data = get_zzz_gacha_data()
    
    return jsonify({
        "last_updated": datetime.now().isoformat(),
        "genshin": genshin_data,
        "hsr": hsr_data,
        "zzz": zzz_data
    })

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='卡池追踪器合并项目')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='服务器主机地址')
    parser.add_argument('--port', type=int, default=5000, help='服务器端口')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    args = parser.parse_args()
    
    print(f"启动卡池追踪器服务器: http://{args.host}:{args.port}")
    print(f"API接口:")
    print(f"  - 原神: http://{args.host}:{args.port}/api/genshin")
    print(f"  - 星穹铁道: http://{args.host}:{args.port}/api/hsr")
    print(f"  - 绝区零: http://{args.host}:{args.port}/api/zzz")
    print(f"  - 所有游戏: http://{args.host}:{args.port}/api/all")
    print(f"  - 健康检查: http://{args.host}:{args.port}/health")
    
    app.run(host=args.host, port=args.port, debug=args.debug)
