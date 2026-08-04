#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
双色球历史数据完整分析脚本
数据源：中国福利彩票官网API
"""

import csv
import json
import math
import time
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from urllib.request import Request, urlopen
from urllib.parse import urlencode


# ==================== 数据爬取 ====================

def fetch_ssq_page(page=1, page_size=100):
    """从福彩官网API获取一页双色球数据"""
    base_url = 'https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice'
    params = {'name': 'ssq', 'pageNo': page, 'pageSize': page_size, 'systemType': 'PC'}
    full_url = base_url + '?' + urlencode(params)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.cwl.gov.cn/',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    req = Request(full_url, headers=headers)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                raise


def crawl_ssq_data(years=10):
    """爬取指定年数的双色球数据"""
    all_data = []
    page_size = 100
    cutoff_date = datetime.now() - timedelta(days=years * 365)
    
    # 获取第一页
    first_page = fetch_ssq_page(1, page_size)
    total_pages = first_page.get('pageNum', 0)
    
    # 处理第一页
    for item in first_page.get('result', []):
        record = parse_record(item)
        if record:
            all_data.append(record)
    
    # 检查是否需要继续
    if all_data:
        last_date = datetime.strptime(all_data[-1]['开奖日期'], '%Y-%m-%d')
        if last_date < cutoff_date:
            return filter_by_date(all_data, cutoff_date)
    
    # 继续爬取后续页面
    for page in range(2, total_pages + 1):
        try:
            data = fetch_ssq_page(page, page_size)
            result = data.get('result', [])
            
            if not result:
                break
            
            oldest_date = None
            for item in result:
                record = parse_record(item)
                if record:
                    all_data.append(record)
                    item_date = datetime.strptime(record['开奖日期'], '%Y-%m-%d')
                    if oldest_date is None or item_date < oldest_date:
                        oldest_date = item_date
            
            if oldest_date and oldest_date < cutoff_date:
                break
            
            time.sleep(0.3)
        except Exception as e:
            print(f"第{page}页出错: {e}")
            time.sleep(2)
            continue
    
    return filter_by_date(all_data, cutoff_date)


def parse_record(item):
    """解析单条记录"""
    try:
        date_str = item.get('date', '').split('(')[0]
        red = item.get('red', '').split(',')
        blue = item.get('blue', '')
        
        if len(red) != 6 or not blue:
            return None
        
        # 红球排序
        red = sorted([int(x) for x in red])
        
        # 一等奖信息
        first_count = ''
        first_money = ''
        for grade in item.get('prizegrades', []):
            if grade.get('type') == 1:
                first_count = grade.get('typenum', '')
                first_money = grade.get('typemoney', '')
                break
        
        return {
            '期号': item.get('code', ''),
            '开奖日期': date_str,
            '红球': red,
            '蓝球': int(blue),
            '销售额': int(item.get('sales', 0)) if item.get('sales') else 0,
            '奖池金额': int(item.get('poolmoney', 0)) if item.get('poolmoney') else 0,
            '一等奖注数': int(first_count) if first_count and first_count.isdigit() else 0,
            '一等奖金额': int(first_money) if first_money and first_money.isdigit() else 0
        }
    except Exception:
        return None


def filter_by_date(data, cutoff_date):
    """按日期过滤"""
    return [d for d in data if datetime.strptime(d['开奖日期'], '%Y-%m-%d') >= cutoff_date]


def save_to_csv(data, filename):
    """保存到CSV"""
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)
        writer.writerow(['期号', '开奖日期', '红球1', '红球2', '红球3', '红球4', '红球5', '红球6', 
                        '蓝球', '销售额(元)', '奖池金额(元)', '一等奖注数', '一等奖单注金额(元)'])
        for d in data:
            writer.writerow([
                d['期号'], d['开奖日期'],
                f"{d['红球'][0]:02d}", f"{d['红球'][1]:02d}", f"{d['红球'][2]:02d}",
                f"{d['红球'][3]:02d}", f"{d['红球'][4]:02d}", f"{d['红球'][5]:02d}",
                f"{d['蓝球']:02d}",
                d['销售额'], d['奖池金额'], d['一等奖注数'], d['一等奖金额']
            ])


# ==================== 数据分析 ====================

class SSQAnalyzer:
    def __init__(self, data):
        self.data = sorted(data, key=lambda x: x['期号'])  # 按期号升序
        self.total = len(data)
        
        # 红球质数定义
        self.red_primes = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}
        
    def data_overview(self):
        """数据概览与清洗检查"""
        issues = [d['期号'] for d in self.data]
        dates = [d['开奖日期'] for d in self.data]
        
        result = {
            '总期数': self.total,
            '起始日期': dates[0],
            '结束日期': dates[-1],
            '起始期号': issues[0],
            '结束期号': issues[-1],
        }
        
        # 异常检查
        anomalies = []
        
        # 重复期号
        issue_counts = Counter(issues)
        dup_issues = [k for k, v in issue_counts.items() if v > 1]
        if dup_issues:
            anomalies.append(f"重复期号: {dup_issues}")
        
        # 重复日期
        date_counts = Counter(dates)
        dup_dates = [k for k, v in date_counts.items() if v > 1]
        if dup_dates:
            anomalies.append(f"重复开奖日期: {dup_dates}")
        
        # 红球检查
        for d in self.data:
            red = d['红球']
            if len(red) != 6:
                anomalies.append(f"期号{d['期号']}: 红球数量不等于6 ({len(red)}个)")
            if any(r < 1 or r > 33 for r in red):
                anomalies.append(f"期号{d['期号']}: 红球超出1-33范围")
            if len(set(red)) != 6:
                anomalies.append(f"期号{d['期号']}: 红球有重复")
        
        # 蓝球检查
        for d in self.data:
            if d['蓝球'] < 1 or d['蓝球'] > 16:
                anomalies.append(f"期号{d['期号']}: 蓝球超出1-16范围")
        
        # 数值字段检查
        for d in self.data:
            if d['销售额'] <= 0:
                anomalies.append(f"期号{d['期号']}: 销售额异常 ({d['销售额']})")
            if d['奖池金额'] < 0:
                anomalies.append(f"期号{d['期号']}: 奖池金额异常 ({d['奖池金额']})")
        
        result['异常情况'] = anomalies if anomalies else ["无异常，数据完整"]
        return result
    
    def red_frequency(self):
        """红球频次统计"""
        counter = Counter()
        for d in self.data:
            counter.update(d['红球'])
        
        result = {}
        avg = self.total * 6 / 33  # 理论平均
        
        for num in range(1, 34):
            count = counter.get(num, 0)
            deviation = count - avg
            dev_pct = (deviation / avg) * 100
            result[num] = {
                '出现次数': count,
                '理论平均': round(avg, 2),
                '偏离值': round(deviation, 2),
                '偏离百分比': round(dev_pct, 2)
            }
        
        # 按频次排序
        sorted_by_count = sorted(result.items(), key=lambda x: x[1]['出现次数'], reverse=True)
        
        # 高/中/低频划分 (前20%/中60%/后20%)
        n = 33
        high_n = round(n * 0.2)
        low_n = round(n * 0.2)
        
        high_freq = [x[0] for x in sorted_by_count[:high_n]]
        low_freq = [x[0] for x in sorted_by_count[-low_n:]]
        normal_freq = [x[0] for x in sorted_by_count[high_n:-low_n]]
        
        return {
            '详细数据': result,
            '按频次排序': sorted_by_count,
            '高频号': sorted(high_freq),
            '正常频率号': sorted(normal_freq),
            '低频号': sorted(low_freq),
            '划分标准': '前20%为高频，中间60%为正常频率，后20%为低频',
            '理论平均': round(avg, 2)
        }
    
    def blue_frequency(self):
        """蓝球频次统计"""
        counter = Counter()
        for d in self.data:
            counter[d['蓝球']] += 1
        
        result = {}
        avg = self.total / 16
        
        for num in range(1, 17):
            count = counter.get(num, 0)
            deviation = count - avg
            dev_pct = (deviation / avg) * 100
            result[num] = {
                '出现次数': count,
                '理论平均': round(avg, 2),
                '偏离值': round(deviation, 2),
                '偏离百分比': round(dev_pct, 2)
            }
        
        sorted_by_count = sorted(result.items(), key=lambda x: x[1]['出现次数'], reverse=True)
        
        n = 16
        high_n = round(n * 0.2)
        low_n = round(n * 0.2)
        
        high_freq = [x[0] for x in sorted_by_count[:high_n]]
        low_freq = [x[0] for x in sorted_by_count[-low_n:]]
        normal_freq = [x[0] for x in sorted_by_count[high_n:-low_n]]
        
        # 遗漏统计
        omission = self._blue_omission()
        
        return {
            '详细数据': result,
            '按频次排序': sorted_by_count,
            '高频号': sorted(high_freq),
            '正常频率号': sorted(normal_freq),
            '低频号': sorted(low_freq),
            '划分标准': '前20%为高频，中间60%为正常频率，后20%为低频',
            '理论平均': round(avg, 2),
            '遗漏统计': omission
        }
    
    def _blue_omission(self):
        """蓝球遗漏统计"""
        last_appear = {}
        current_omission = {}
        max_omission = defaultdict(int)
        all_omissions = defaultdict(list)
        
        for i, d in enumerate(self.data):
            blue = d['蓝球']
            # 更新所有蓝球的当前遗漏
            for num in range(1, 17):
                if num != blue:
                    current_omission[num] = current_omission.get(num, 0) + 1
                else:
                    if num in current_omission:
                        all_omissions[num].append(current_omission[num])
                        if current_omission[num] > max_omission[num]:
                            max_omission[num] = current_omission[num]
                    current_omission[num] = 0
                    last_appear[num] = i
        
        # 当前遗漏（从最后一期到现在）
        now_omission = {}
        last_idx = len(self.data) - 1
        for num in range(1, 17):
            if num in last_appear:
                now_omission[num] = last_idx - last_appear[num]
            else:
                now_omission[num] = self.total
        
        # 平均遗漏
        avg_omission = {}
        for num in range(1, 17):
            omissions = all_omissions[num]
            if omissions:
                avg_omission[num] = round(sum(omissions) / len(omissions), 1)
            else:
                avg_omission[num] = 0
        
        return {
            '当前遗漏': now_omission,
            '最大遗漏': dict(max_omission),
            '平均遗漏': avg_omission
        }
    
    def red_morphology(self):
        """红球形态统计"""
        results = {}
        
        # 1. 奇偶配比
        odd_even = Counter()
        for d in self.data:
            odd_count = sum(1 for r in d['红球'] if r % 2 == 1)
            even_count = 6 - odd_count
            odd_even[f"{odd_count}奇{even_count}偶"] += 1
        results['奇偶配比'] = dict(odd_even.most_common())
        
        # 2. 大小号分布 (1-16小, 17-33大)
        big_small = Counter()
        for d in self.data:
            small = sum(1 for r in d['红球'] if r <= 16)
            big = 6 - small
            big_small[f"{small}小{big}大"] += 1
        results['大小分布'] = dict(big_small.most_common())
        
        # 3. 三区分布 (1-11, 12-22, 23-33)
        three_zones = Counter()
        for d in self.data:
            z1 = sum(1 for r in d['红球'] if 1 <= r <= 11)
            z2 = sum(1 for r in d['红球'] if 12 <= r <= 22)
            z3 = sum(1 for r in d['红球'] if 23 <= r <= 33)
            three_zones[f"{z1}-{z2}-{z3}"] += 1
        results['三区分布'] = dict(three_zones.most_common(15))
        
        # 4. 连号分布
        consecutive = Counter()
        for d in self.data:
            red = sorted(d['红球'])
            # 找所有连号组
            groups = []
            current_group = [red[0]]
            for i in range(1, 6):
                if red[i] == red[i-1] + 1:
                    current_group.append(red[i])
                else:
                    if len(current_group) >= 2:
                        groups.append(len(current_group))
                    current_group = [red[i]]
            if len(current_group) >= 2:
                groups.append(len(current_group))
            
            # 分类
            if not groups:
                consecutive['无连号'] += 1
            elif len(groups) == 1 and groups[0] == 2:
                consecutive['1组二连号'] += 1
            elif len(groups) == 2 and all(g == 2 for g in groups):
                consecutive['2组二连号'] += 1
            elif len(groups) == 1 and groups[0] == 3:
                consecutive['1组三连号'] += 1
            elif len(groups) == 1 and groups[0] == 4:
                consecutive['1组四连号'] += 1
            elif len(groups) == 1 and groups[0] == 5:
                consecutive['1组五连号'] += 1
            elif len(groups) == 1 and groups[0] == 6:
                consecutive['6连号'] += 1
            elif len(groups) == 2 and 3 in groups:
                consecutive['1组三连+1组二连'] += 1
            else:
                consecutive[f'其他({len(groups)}组)'] += 1
        results['连号分布'] = dict(consecutive.most_common())
        
        # 5. 和值分布
        sums = [sum(d['红球']) for d in self.data]
        sums_sorted = sorted(sums)
        n = len(sums)
        results['和值统计'] = {
            '最小': min(sums),
            '最大': max(sums),
            '平均': round(sum(sums) / n, 1),
            '中位数': sums_sorted[n // 2],
            'Q1': sums_sorted[n // 4],
            'Q3': sums_sorted[3 * n // 4],
            'P10': sums_sorted[n // 10],
            'P90': sums_sorted[9 * n // 10],
        }
        # 和值区间分布
        sum_ranges = Counter()
        for s in sums:
            if s <= 70:
                sum_ranges['21-70(极低)'] += 1
            elif s <= 90:
                sum_ranges['71-90(低)'] += 1
            elif s <= 110:
                sum_ranges['91-110(中低)'] += 1
            elif s <= 130:
                sum_ranges['111-130(中)'] += 1
            elif s <= 150:
                sum_ranges['131-150(中高)'] += 1
            elif s <= 170:
                sum_ranges['151-170(高)'] += 1
            else:
                sum_ranges['171-183(极高)'] += 1
        results['和值区间分布'] = dict(sum_ranges.most_common())
        
        # 6. 跨度分布
        spans = [d['红球'][-1] - d['红球'][0] for d in self.data]
        spans_sorted = sorted(spans)
        results['跨度统计'] = {
            '最小': min(spans),
            '最大': max(spans),
            '平均': round(sum(spans) / n, 1),
            '中位数': spans_sorted[n // 2],
        }
        # 跨度区间
        span_ranges = Counter()
        for s in spans:
            if s <= 10:
                span_ranges['5-10(极小)'] += 1
            elif s <= 15:
                span_ranges['11-15(小)'] += 1
            elif s <= 20:
                span_ranges['16-20(中)'] += 1
            elif s <= 25:
                span_ranges['21-25(大)'] += 1
            else:
                span_ranges['26-32(极大)'] += 1
        results['跨度区间分布'] = dict(span_ranges.most_common())
        
        # 7. 质数/合数分布
        prime_composite = Counter()
        has_one_count = 0
        for d in self.data:
            prime_count = sum(1 for r in d['红球'] if r in self.red_primes)
            has_one = 1 in d['红球']
            if has_one:
                has_one_count += 1
            composite_count = 6 - prime_count - (1 if has_one else 0)
            prime_composite[f"{prime_count}质{composite_count}合{'含1' if has_one else ''}"] += 1
        results['质合分布'] = dict(prime_composite.most_common(10))
        results['含1的期数'] = has_one_count
        
        # 8. 尾号分布
        tail_counter = Counter()
        same_tail_count = Counter()  # 同尾号组数
        for d in self.data:
            tails = [r % 10 for r in d['红球']]
            tail_counter.update(tails)
            tail_counts = Counter(tails)
            same_tail_groups = sum(1 for v in tail_counts.values() if v >= 2)
            same_tail_count[same_tail_groups] += 1
        results['尾号频次'] = dict(tail_counter)
        results['同尾号组数分布'] = {f"{k}组同尾": v for k, v in same_tail_count.most_common()}
        
        # 9. 重号分布
        repeat_counts = Counter()
        for i in range(1, len(self.data)):
            prev_red = set(self.data[i-1]['红球'])
            curr_red = set(self.data[i]['红球'])
            repeat = len(prev_red & curr_red)
            repeat_counts[repeat] += 1
        results['重号分布'] = {f"{k}个重号": v for k, v in sorted(repeat_counts.items())}
        
        # 10. 邻号分布
        neighbor_counts = Counter()
        for i in range(1, len(self.data)):
            prev_red = set(self.data[i-1]['红球'])
            curr_red = set(self.data[i]['红球'])
            neighbors = 0
            for r in curr_red:
                if (r - 1) in prev_red or (r + 1) in prev_red:
                    neighbors += 1
            neighbor_counts[neighbors] += 1
        results['邻号分布'] = {f"{k}个邻号": v for k, v in sorted(neighbor_counts.items())}
        
        return results
    
    def blue_morphology(self):
        """蓝球形态统计"""
        results = {}
        
        blues = [d['蓝球'] for d in self.data]
        
        # 奇偶
        odd = sum(1 for b in blues if b % 2 == 1)
        even = self.total - odd
        results['奇偶分布'] = {
            '奇数': odd,
            '偶数': even,
            '奇数占比': f"{odd/self.total*100:.1f}%",
            '偶数占比': f"{even/self.total*100:.1f}%",
        }
        
        # 大小 (1-8小, 9-16大)
        small = sum(1 for b in blues if b <= 8)
        big = self.total - small
        results['大小分布'] = {
            '小号(1-8)': small,
            '大号(9-16)': big,
            '小号占比': f"{small/self.total*100:.1f}%",
            '大号占比': f"{big/self.total*100:.1f}%",
        }
        
        return results
    
    def sales_stats(self):
        """销售额、奖池与一等奖统计"""
        sales = [d['销售额'] for d in self.data]
        pool = [d['奖池金额'] for d in self.data]
        first_counts = [d['一等奖注数'] for d in self.data]
        first_moneys = [d['一等奖金额'] for d in self.data if d['一等奖金额'] > 0]
        
        sales_sorted = sorted(sales)
        pool_sorted = sorted(pool)
        
        n = self.total
        
        # 销售额统计
        max_sale_idx = sales.index(max(sales))
        min_sale_idx = sales.index(min(sales))
        
        sales_stats = {
            '平均销售额': f"{sum(sales)/n/1e8:.2f}亿元",
            '中位数销售额': f"{sales_sorted[n//2]/1e8:.2f}亿元",
            '最高销售额': f"{max(sales)/1e8:.2f}亿元",
            '最高销售额期号': self.data[max_sale_idx]['期号'],
            '最高销售额日期': self.data[max_sale_idx]['开奖日期'],
            '最低销售额': f"{min(sales)/1e8:.2f}亿元",
            '最低销售额期号': self.data[min_sale_idx]['期号'],
            '最低销售额日期': self.data[min_sale_idx]['开奖日期'],
        }
        
        # 奖池统计
        max_pool_idx = pool.index(max(pool))
        min_pool_idx = pool.index(min(pool))
        
        pool_stats = {
            '平均奖池': f"{sum(pool)/n/1e8:.2f}亿元",
            '中位数奖池': f"{pool_sorted[n//2]/1e8:.2f}亿元",
            '最高奖池': f"{max(pool)/1e8:.2f}亿元",
            '最高奖池期号': self.data[max_pool_idx]['期号'],
            '最高奖池日期': self.data[max_pool_idx]['开奖日期'],
            '最低奖池': f"{min(pool)/1e8:.2f}亿元",
            '最低奖池期号': self.data[min_pool_idx]['期号'],
            '最低奖池日期': self.data[min_pool_idx]['开奖日期'],
        }
        
        # 一等奖统计
        first_count_stats = Counter(first_counts)
        zero_first = first_counts.count(0)
        one_first = first_counts.count(1)
        few_first = sum(1 for c in first_counts if 2 <= c <= 5)
        many_first = sum(1 for c in first_counts if c > 5)
        
        first_stats = {
            '注数分布': dict(sorted(first_count_stats.items())[:15]),
            '无一等奖期数': zero_first,
            '1注一等奖期数': one_first,
            '2-5注一等奖期数': few_first,
            '5注以上期数': many_first,
            '一等奖单注平均金额': f"{sum(first_moneys)/len(first_moneys)/1e4:.2f}万元" if first_moneys else 'N/A',
            '一等奖单注中位数金额': f"{sorted(first_moneys)[len(first_moneys)//2]/1e4:.2f}万元" if first_moneys else 'N/A',
            '一等奖单注最高金额': f"{max(first_moneys)/1e4:.2f}万元" if first_moneys else 'N/A',
            '一等奖单注最低金额': f"{min(first_moneys)/1e4:.2f}万元" if first_moneys else 'N/A',
        }
        
        # 相关性（简单描述性）
        # 销售额 vs 一等奖注数
        corr_sale_first = self._correlation(sales, first_counts)
        # 奖池 vs 一等奖金额
        pool_with_money = [pool[i] for i in range(n) if self.data[i]['一等奖金额'] > 0]
        money_with_pool = [self.data[i]['一等奖金额'] for i in range(n) if self.data[i]['一等奖金额'] > 0]
        corr_pool_money = self._correlation(pool_with_money, money_with_pool)
        # 销售额 vs 奖池
        corr_sale_pool = self._correlation(sales, pool)
        
        correlation_stats = {
            '销售额与一等奖注数相关系数': round(corr_sale_first, 3),
            '奖池金额与一等奖单注金额相关系数': round(corr_pool_money, 3),
            '销售额与奖池金额相关系数': round(corr_sale_pool, 3),
            '说明': '相关系数范围-1到1，绝对值越接近1相关性越强，仅为描述性统计，不代表因果关系'
        }
        
        return {
            '销售额统计': sales_stats,
            '奖池统计': pool_stats,
            '一等奖统计': first_stats,
            '相关性分析': correlation_stats
        }
    
    def _correlation(self, x, y):
        """简单皮尔逊相关系数"""
        n = len(x)
        if n < 2:
            return 0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / n
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x) / n)
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y) / n)
        if std_x == 0 or std_y == 0:
            return 0
        return cov / (std_x * std_y)
    
    def chi_square_test(self):
        """卡方检验 - 红球"""
        expected = self.total * 6 / 33
        
        counter = Counter()
        for d in self.data:
            counter.update(d['红球'])
        
        chi_sq = 0
        for num in range(1, 34):
            observed = counter.get(num, 0)
            chi_sq += (observed - expected) ** 2 / expected
        
        # 自由度 = 33 - 1 = 32
        # 卡方分布临界值（近似）
        # df=32, p=0.05 时临界值约为 46.19
        # df=32, p=0.01 时临界值约为 53.49
        
        df = 32
        critical_05 = 46.19
        critical_01 = 53.49
        
        conclusion = ''
        if chi_sq < critical_05:
            conclusion = f'卡方值 {chi_sq:.2f} < 临界值 {critical_05} (p=0.05, df={df})，在0.05显著性水平下，不能拒绝均匀分布假设，号码频次差异可能属于正常随机波动。'
        elif chi_sq < critical_01:
            conclusion = f'卡方值 {chi_sq:.2f} 介于 {critical_05} 和 {critical_01} 之间 (df={df})，在0.05显著性水平下可拒绝均匀分布假设，但在0.01水平下不能拒绝。'
        else:
            conclusion = f'卡方值 {chi_sq:.2f} > 临界值 {critical_01} (p=0.01, df={df})，在0.01显著性水平下可拒绝均匀分布假设。'
        
        # 蓝球卡方
        blue_counter = Counter()
        for d in self.data:
            blue_counter[d['蓝球']] += 1
        
        blue_expected = self.total / 16
        blue_chi_sq = 0
        for num in range(1, 17):
            observed = blue_counter.get(num, 0)
            blue_chi_sq += (observed - blue_expected) ** 2 / blue_expected
        
        blue_df = 15
        blue_critical_05 = 24.996
        blue_critical_01 = 30.578
        
        blue_conclusion = ''
        if blue_chi_sq < blue_critical_05:
            blue_conclusion = f'蓝球卡方值 {blue_chi_sq:.2f} < 临界值 {blue_critical_05} (p=0.05, df={blue_df})，不能拒绝均匀分布假设。'
        else:
            blue_conclusion = f'蓝球卡方值 {blue_chi_sq:.2f}，需进一步判断。'
        
        return {
            '红球卡方值': round(chi_sq, 2),
            '红球自由度': df,
            '红球临界值(p=0.05)': critical_05,
            '红球临界值(p=0.01)': critical_01,
            '红球结论': conclusion,
            '蓝球卡方值': round(blue_chi_sq, 2),
            '蓝球自由度': blue_df,
            '蓝球结论': blue_conclusion
        }
    
    def generate_entertainment_numbers(self, count=10):
        """生成娱乐号码"""
        import random
        
        # 获取历史统计数据
        red_freq = self.red_frequency()
        blue_freq = self.blue_frequency()
        morph = self.red_morphology()
        
        high_red = set(red_freq['高频号'])
        low_red = set(red_freq['低频号'])
        normal_red = set(red_freq['正常频率号'])
        
        high_blue = set(blue_freq['高频号'])
        low_blue = set(blue_freq['低频号'])
        normal_blue = set(blue_freq['正常频率号'])
        
        # 历史红球集合（用于避免重复）
        history_red_sets = set()
        for d in self.data:
            history_red_sets.add(tuple(sorted(d['红球'])))
        
        numbers = []
        attempts = 0
        max_attempts = 10000
        
        while len(numbers) < count and attempts < max_attempts:
            attempts += 1
            
            # 生成红球 - 尽量贴近历史主流形态
            red = self._generate_balanced_red(high_red, normal_red, low_red, morph)
            
            # 检查是否与历史完全重复
            if tuple(sorted(red)) in history_red_sets:
                continue
            
            # 检查是否与已生成的过度相似
            too_similar = False
            for existing in numbers:
                same = len(set(red) & set(existing['红球']))
                if same >= 5:  # 5个以上相同算过度相似
                    too_similar = True
                    break
            if too_similar:
                continue
            
            # 生成蓝球
            blue = self._generate_balanced_blue(high_blue, normal_blue, low_blue)
            
            # 计算形态
            info = self._analyze_number(red, blue)
            numbers.append({
                '红球': sorted(red),
                '蓝球': blue,
                '形态': info
            })
        
        return numbers
    
    def _generate_balanced_red(self, high, normal, low, morph):
        """生成平衡的红球组合"""
        import random
        
        # 策略：混合高、中、低频号
        # 2个高频 + 3个中频 + 1个低频 或类似组合
        
        strategies = [
            (2, 3, 1),  # 2高3中1低
            (1, 4, 1),  # 1高4中1低
            (2, 2, 2),  # 2高2中2低
            (3, 2, 1),  # 3高2中1低
            (1, 3, 2),  # 1高3中2低
        ]
        
        strategy = random.choice(strategies)
        n_high, n_normal, n_low = strategy
        
        # 确保数量正确
        if n_high > len(high):
            n_high = len(high)
        if n_low > len(low):
            n_low = len(low)
        n_normal = 6 - n_high - n_low
        
        selected = set()
        selected.update(random.sample(list(high), min(n_high, len(high))))
        selected.update(random.sample(list(low), min(n_low, len(low))))
        
        remaining = normal - selected
        needed = 6 - len(selected)
        if needed > 0 and len(remaining) >= needed:
            selected.update(random.sample(list(remaining), needed))
        else:
            # 从中高频补充
            pool = (high | normal | low) - selected
            selected.update(random.sample(list(pool), 6 - len(selected)))
        
        red = sorted(selected)
        
        # 形态检查和调整
        # 检查是否极端
        if self._is_extreme(red):
            # 重新生成
            return self._generate_balanced_red(high, normal, low, morph)
        
        return red
    
    def _is_extreme(self, red):
        """判断是否为极端组合"""
        # 全奇/全偶
        odd_count = sum(1 for r in red if r % 2 == 1)
        if odd_count == 0 or odd_count == 6:
            return True
        
        # 全大/全小
        small_count = sum(1 for r in red if r <= 16)
        if small_count == 0 or small_count == 6:
            return True
        
        # 和值极端
        s = sum(red)
        if s < 50 or s > 170:
            return True
        
        # 跨度极端
        span = red[-1] - red[0]
        if span < 10 or span > 30:
            return True
        
        # 6连号
        consecutive = 1
        max_consec = 1
        for i in range(1, 6):
            if red[i] == red[i-1] + 1:
                consecutive += 1
                max_consec = max(max_consec, consecutive)
            else:
                consecutive = 1
        if max_consec >= 6:
            return True
        
        # 过度集中在同一区
        z1 = sum(1 for r in red if r <= 11)
        z2 = sum(1 for r in red if 12 <= r <= 22)
        z3 = sum(1 for r in red if r >= 23)
        if z1 >= 5 or z2 >= 5 or z3 >= 5:
            return True
        
        return False
    
    def _generate_balanced_blue(self, high, normal, low):
        """生成平衡的蓝球"""
        import random
        
        # 随机选择高、中、低频
        r = random.random()
        if r < 0.3:
            pool = high
        elif r < 0.7:
            pool = normal
        else:
            pool = low
        
        if not pool:
            pool = high | normal | low
        
        return random.choice(list(pool))
    
    def _analyze_number(self, red, blue):
        """分析一组号码的形态"""
        red = sorted(red)
        
        # 奇偶比
        odd = sum(1 for r in red if r % 2 == 1)
        odd_ratio = f"{odd}奇{6-odd}偶"
        
        # 大小比
        small = sum(1 for r in red if r <= 16)
        big_small = f"{small}小{6-small}大"
        
        # 三区分布
        z1 = sum(1 for r in red if r <= 11)
        z2 = sum(1 for r in red if 12 <= r <= 22)
        z3 = sum(1 for r in red if r >= 23)
        zones = f"{z1}-{z2}-{z3}"
        
        # 和值
        sum_val = sum(red)
        
        # 跨度
        span = red[-1] - red[0]
        
        # 连号
        consecutive_groups = []
        current = [red[0]]
        for i in range(1, 6):
            if red[i] == red[i-1] + 1:
                current.append(red[i])
            else:
                if len(current) >= 2:
                    consecutive_groups.append(len(current))
                current = [red[i]]
        if len(current) >= 2:
            consecutive_groups.append(len(current))
        
        if not consecutive_groups:
            consecutive_desc = '无连号'
        else:
            desc_parts = []
            for g in consecutive_groups:
                if g == 2:
                    desc_parts.append('二连')
                elif g == 3:
                    desc_parts.append('三连')
                else:
                    desc_parts.append(f'{g}连')
            consecutive_desc = f"{len(consecutive_groups)}组" + '+'.join(desc_parts)
        
        # 蓝球形态
        blue_odd = '奇' if blue % 2 == 1 else '偶'
        blue_size = '小' if blue <= 8 else '大'
        
        return {
            '奇偶比': odd_ratio,
            '大小比': big_small,
            '三区分布': zones,
            '和值': sum_val,
            '跨度': span,
            '连号情况': consecutive_desc,
            '蓝球形态': f"{blue_odd}数/{blue_size}号"
        }


def main():
    print("正在爬取近10年双色球数据...")
    data = crawl_ssq_data(years=10)
    print(f"爬取完成，共 {len(data)} 期数据")
    
    # 保存CSV
    save_to_csv(data, '双色球近10年历史数据.csv')
    print("数据已保存到 双色球近10年历史数据.csv")
    
    # 分析
    print("\n开始数据分析...")
    analyzer = SSQAnalyzer(data)
    
    # 保存分析结果到文件
    result = {
        '数据概览': analyzer.data_overview(),
        '红球频次': analyzer.red_frequency(),
        '蓝球频次': analyzer.blue_frequency(),
        '红球形态': analyzer.red_morphology(),
        '蓝球形态': analyzer.blue_morphology(),
        '销售奖池统计': analyzer.sales_stats(),
        '卡方检验': analyzer.chi_square_test(),
        '娱乐号码': analyzer.generate_entertainment_numbers(10),
    }
    
    # 输出到JSON文件（供后续使用）
    with open('analysis_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    
    print("分析完成，结果已保存到 analysis_result.json")
    print(f"\n数据概览:")
    print(f"  总期数: {result['数据概览']['总期数']}")
    print(f"  时间范围: {result['数据概览']['起始日期']} ~ {result['数据概览']['结束日期']}")
    print(f"  异常: {result['数据概览']['异常情况'][0]}")
    print(f"\n红球高频号: {result['红球频次']['高频号']}")
    print(f"红球低频号: {result['红球频次']['低频号']}")
    print(f"\n蓝球高频号: {result['蓝球频次']['高频号']}")
    print(f"蓝球低频号: {result['蓝球频次']['低频号']}")


if __name__ == '__main__':
    main()
