#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
双色球历史开奖号码爬虫
数据源：中国福利彩票官网API
输出：CSV文件
"""

import csv
import json
import time
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def fetch_ssq_page(page=1, page_size=100):
    """从福彩官网API获取一页双色球数据"""
    base_url = 'https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice'
    
    params = {
        'name': 'ssq',
        'pageNo': page,
        'pageSize': page_size,
        'systemType': 'PC'
    }
    
    full_url = base_url + '?' + urlencode(params)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.cwl.gov.cn/',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest'
    }
    
    req = Request(full_url, headers=headers)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"  第{attempt+1}次请求失败，重试中... ({e})")
                time.sleep(2)
            else:
                raise


def crawl_ssq_history(years=5):
    """
    爬取双色球历史数据
    :param years: 爬取最近几年的数据
    :return: 数据列表
    """
    all_data = []
    page_size = 100
    page = 1
    
    # 计算截止日期
    cutoff_date = datetime.now() - timedelta(days=years * 365)
    print(f"目标：爬取 {cutoff_date.strftime('%Y-%m-%d')} 至今的双色球开奖数据")
    print(f"数据源：中国福利彩票官网 API")
    print("=" * 60)
    
    # 先获取第一页，看看总记录数
    first_page = fetch_ssq_page(1, page_size)
    total = first_page.get('total', 0)
    total_pages = first_page.get('pageNum', 0)
    
    print(f"总期数：{total} 期，总页数：{total_pages} 页（每页 {page_size} 条）")
    print()
    
    # 处理第一页数据
    result = first_page.get('result', [])
    for item in result:
        record = parse_record(item)
        if record:
            all_data.append(record)
    
    print(f"第 1 页：获取 {len(result)} 条，累计 {len(all_data)} 条")
    
    # 检查第一页是否已经到了截止日期
    if all_data:
        last_date_str = all_data[-1]['开奖日期']
        last_date = datetime.strptime(last_date_str, '%Y-%m-%d')
        if last_date < cutoff_date:
            print(f"第一页已覆盖到 {years} 年前的数据，停止爬取")
            return filter_by_date(all_data, cutoff_date)
    
    # 继续爬取后续页面
    for page in range(2, total_pages + 1):
        try:
            print(f"正在爬取第 {page} 页...", end=' ', flush=True)
            
            data = fetch_ssq_page(page, page_size)
            result = data.get('result', [])
            
            if not result:
                print("无数据，停止爬取")
                break
            
            new_count = 0
            oldest_date = None
            
            for item in result:
                record = parse_record(item)
                if record:
                    all_data.append(record)
                    new_count += 1
                    
                    item_date = datetime.strptime(record['开奖日期'], '%Y-%m-%d')
                    if oldest_date is None or item_date < oldest_date:
                        oldest_date = item_date
            
            print(f"获取 {len(result)} 条，累计 {len(all_data)} 条")
            
            # 检查是否已经到了截止日期
            if oldest_date and oldest_date < cutoff_date:
                print(f"已到达 {years} 年前的数据（最旧：{oldest_date.strftime('%Y-%m-%d')}），停止爬取")
                break
            
            time.sleep(0.3)  # 礼貌延时
            
        except Exception as e:
            print(f"第 {page} 页出错: {e}")
            time.sleep(2)
            continue
    
    # 按日期过滤
    filtered_data = filter_by_date(all_data, cutoff_date)
    
    # 按期号降序排列（最新的在前）
    filtered_data.sort(key=lambda x: x['期号'], reverse=True)
    
    return filtered_data


def parse_record(item):
    """解析单条记录"""
    try:
        # 解析日期，去掉括号里的星期
        date_str = item.get('date', '')
        # 格式如: 2026-07-28(二)
        if '(' in date_str:
            date_str = date_str.split('(')[0]
        
        # 解析红球
        red = item.get('red', '')
        red_balls = red.split(',') if red else []
        
        # 解析蓝球
        blue = item.get('blue', '')
        
        if len(red_balls) != 6 or not blue:
            return None
        
        # 获取一等奖信息
        first_prize_count = ''
        first_prize_money = ''
        prizegrades = item.get('prizegrades', [])
        if prizegrades:
            for grade in prizegrades:
                if grade.get('type') == 1:
                    first_prize_count = grade.get('typenum', '')
                    first_prize_money = grade.get('typemoney', '')
                    break
        
        return {
            '期号': item.get('code', ''),
            '开奖日期': date_str,
            '红球1': red_balls[0],
            '红球2': red_balls[1],
            '红球3': red_balls[2],
            '红球4': red_balls[3],
            '红球5': red_balls[4],
            '红球6': red_balls[5],
            '蓝球': blue,
            '销售额(元)': item.get('sales', ''),
            '奖池金额(元)': item.get('poolmoney', ''),
            '一等奖注数': first_prize_count,
            '一等奖单注金额(元)': first_prize_money
        }
    except Exception as e:
        print(f"解析记录失败: {e}")
        return None


def filter_by_date(data, cutoff_date):
    """按日期过滤数据"""
    filtered = []
    for item in data:
        try:
            item_date = datetime.strptime(item['开奖日期'], '%Y-%m-%d')
            if item_date >= cutoff_date:
                filtered.append(item)
        except ValueError:
            continue
    return filtered


def save_to_csv(data, filename='双色球历史开奖号码.csv'):
    """保存数据到CSV文件"""
    if not data:
        print("没有数据可保存")
        return
    
    fieldnames = [
        '期号', '开奖日期', 
        '红球1', '红球2', '红球3', '红球4', '红球5', '红球6', '蓝球',
        '销售额(元)', '奖池金额(元)', '一等奖注数', '一等奖单注金额(元)'
    ]
    
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
    
    print()
    print("=" * 60)
    print(f"数据已保存到: {filename}")
    print(f"共 {len(data)} 期数据")
    print(f"时间范围: {data[-1]['开奖日期']} ~ {data[0]['开奖日期']}")
    print("=" * 60)


def main():
    print()
    print("=" * 60)
    print("  双色球历史开奖号码爬虫")
    print("  数据源：中国福利彩票官网")
    print("=" * 60)
    print()
    
    # 爬取最近5年数据
    data = crawl_ssq_history(years=5)
    
    # 保存到CSV
    save_to_csv(data)
    
    # 打印前5条和后5条预览
    if data:
        print()
        print("最新5期预览：")
        print("-" * 60)
        for item in data[:5]:
            red = ' '.join([item[f'红球{i}'] for i in range(1, 7)])
            print(f"  {item['期号']}  {item['开奖日期']}  红球: {red}  蓝球: {item['蓝球']}")
        
        print()
        print("最早5期预览：")
        print("-" * 60)
        for item in data[-5:]:
            red = ' '.join([item[f'红球{i}'] for i in range(1, 7)])
            print(f"  {item['期号']}  {item['开奖日期']}  红球: {red}  蓝球: {item['蓝球']}")


if __name__ == '__main__':
    main()
