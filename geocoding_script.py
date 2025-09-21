#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Maps Geocoding Script
สำหรับค้นหาพิกัดจาก location + subdistrict
"""

import pandas as pd
import requests
import time
import json
from typing import Dict, List, Tuple, Optional
import logging

# ตั้งค่า logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GoogleMapsGeocoder:
    def __init__(self, api_key: str):
        """
        Initialize Google Maps Geocoder
        
        Args:
            api_key (str): Google Maps API Key
        """
        self.api_key = api_key
        self.base_url = "https://maps.googleapis.com/maps/api/geocode/json"
        self.session = requests.Session()
        
    def geocode_address(self, address: str, region: str = "th") -> Optional[Dict]:
        """
        Geocode ข้อมูลที่อยู่
        
        Args:
            address (str): ที่อยู่ที่ต้องการ geocode
            region (str): ภูมิภาค (default: "th" สำหรับประเทศไทย)
            
        Returns:
            Dict: ข้อมูลพิกัดและข้อมูลเพิ่มเติม หรือ None หากไม่พบ
        """
        params = {
            'address': address,
            'key': self.api_key,
            'region': region,
            'language': 'th'
        }
        
        try:
            response = self.session.get(self.base_url, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            if data['status'] == 'OK' and data['results']:
                result = data['results'][0]
                return {
                    'formatted_address': result['formatted_address'],
                    'latitude': result['geometry']['location']['lat'],
                    'longitude': result['geometry']['location']['lng'],
                    'place_id': result['place_id'],
                    'types': result['types'],
                    'status': data['status']
                }
            else:
                logger.warning(f"ไม่พบข้อมูลสำหรับ: {address} - Status: {data['status']}")
                return {
                    'formatted_address': None,
                    'latitude': None,
                    'longitude': None,
                    'place_id': None,
                    'types': None,
                    'status': data['status']
                }
                
        except requests.exceptions.RequestException as e:
            logger.error(f"เกิดข้อผิดพลาดในการเรียก API: {e}")
            return None
        except Exception as e:
            logger.error(f"เกิดข้อผิดพลาด: {e}")
            return None

def process_station_data(input_file: str, output_file: str, api_key: str, 
                        batch_size: int = 10, delay: float = 0.1, 
                        start_row: int = 0, end_row: int = None, 
                        insert_mode: bool = True):
    """
    ประมวลผลข้อมูลสถานีเลือกตั้งและเพิ่มข้อมูลพิกัด
    
    Args:
        input_file (str): ไฟล์ CSV ข้อมูลสถานี
        output_file (str): ไฟล์ CSV ข้อมูลผลลัพธ์ (ใช้เป็นไฟล์เดียวกันกับ input_file หากเป็น insert_mode)
        api_key (str): Google Maps API Key
        batch_size (int): จำนวนแถวที่ประมวลผลต่อครั้ง
        delay (float): หน่วงเวลาระหว่างการเรียก API (วินาที)
        start_row (int): แถวเริ่มต้นที่ต้องการประมวลผล (0-based)
        end_row (int): แถวสิ้นสุดที่ต้องการประมวลผล (None = จนถึงแถวสุดท้าย)
        insert_mode (bool): True = insert ข้อมูลในไฟล์เดิม, False = สร้างไฟล์ใหม่
    """
    # อ่านข้อมูล CSV
    logger.info(f"กำลังอ่านข้อมูลจากไฟล์: {input_file}")
    df = pd.read_csv(input_file)
    
    # กำหนดแถวที่ต้องการประมวลผล
    if end_row is None:
        end_row = len(df)
    
    # ตรวจสอบขอบเขตแถว
    if start_row < 0 or start_row >= len(df):
        raise ValueError(f"แถวเริ่มต้น ({start_row}) ไม่อยู่ในช่วงที่ถูกต้อง (0-{len(df)-1})")
    if end_row <= start_row or end_row > len(df):
        raise ValueError(f"แถวสิ้นสุด ({end_row}) ไม่อยู่ในช่วงที่ถูกต้อง ({start_row+1}-{len(df)})")
    
    total_rows = end_row - start_row
    logger.info(f"จะประมวลผลแถว {start_row+1} ถึง {end_row} (ทั้งหมด {total_rows} แถว)")
    
    # สร้าง geocoder
    geocoder = GoogleMapsGeocoder(api_key)
    
    # เพิ่มคอลัมน์ใหม่สำหรับข้อมูล geocoding (เฉพาะแถวที่ยังไม่มี)
    if 'search_address' not in df.columns:
        df['search_address'] = df['location'] + " " + df['subdistrict']
    else:
        # อัปเดต search_address สำหรับแถวที่ยังไม่มี
        mask = df['search_address'].isna()
        df.loc[mask, 'search_address'] = df.loc[mask, 'location'] + " " + df.loc[mask, 'subdistrict']
    
    # เพิ่มคอลัมน์อื่น ๆ หากยังไม่มี
    for col in ['formatted_address', 'latitude', 'longitude', 'place_id', 'geocoding_status', 'geocoding_types']:
        if col not in df.columns:
            df[col] = None
    
    logger.info(f"พบข้อมูลทั้งหมด {total_rows} แถวที่จะประมวลผล")
    
    # ประมวลผลข้อมูลทีละ batch (เฉพาะแถวที่ยังไม่มีข้อมูล geocoding)
    processed_count = 0
    for i in range(start_row, end_row, batch_size):
        end_idx = min(i + batch_size, end_row)
        
        logger.info(f"กำลังประมวลผลแถว {i+1}-{end_idx} จาก {start_row+1}-{end_row}")
        
        for idx in range(i, end_idx):
            # ข้ามแถวที่มีข้อมูล geocoding อยู่แล้ว (ยกเว้น status เป็น ERROR)
            if (pd.notna(df.at[idx, 'latitude']) and 
                pd.notna(df.at[idx, 'longitude']) and 
                df.at[idx, 'geocoding_status'] != 'ERROR'):
                logger.info(f"⏭️  ข้ามแถว {idx+1} (มีข้อมูลแล้ว): {df.at[idx, 'search_address']}")
                continue
            
            search_address = df.at[idx, 'search_address']
            
            # เรียก geocoding API
            result = geocoder.geocode_address(search_address)
            
            if result:
                df.at[idx, 'formatted_address'] = result['formatted_address']
                df.at[idx, 'latitude'] = result['latitude']
                df.at[idx, 'longitude'] = result['longitude']
                df.at[idx, 'place_id'] = result['place_id']
                df.at[idx, 'geocoding_status'] = result['status']
                df.at[idx, 'geocoding_types'] = ', '.join(result['types']) if result['types'] else None
                
                logger.info(f"✓ พบพิกัดสำหรับแถว {idx+1}: {search_address}")
            else:
                df.at[idx, 'geocoding_status'] = 'ERROR'
                logger.warning(f"✗ ไม่พบพิกัดสำหรับแถว {idx+1}: {search_address}")
            
            processed_count += 1
            
            # หน่วงเวลาเพื่อไม่ให้เกิน rate limit
            time.sleep(delay)
        
        # บันทึกข้อมูลชั่วคราวทุก batch
        if insert_mode:
            temp_file = f"{input_file}.temp"
            df.to_csv(temp_file, index=False, encoding='utf-8')
            logger.info(f"บันทึกข้อมูลชั่วคราวที่: {temp_file}")
        else:
            temp_file = f"{output_file}.temp"
            df.to_csv(temp_file, index=False, encoding='utf-8')
            logger.info(f"บันทึกข้อมูลชั่วคราวที่: {temp_file}")
    
    # บันทึกไฟล์สุดท้าย
    if insert_mode:
        final_output_file = input_file  # ใช้ไฟล์เดิม
        df.to_csv(final_output_file, index=False, encoding='utf-8')
        logger.info(f"บันทึกข้อมูลสุดท้ายที่: {final_output_file}")
        
        # ลบไฟล์ชั่วคราว
        import os
        temp_file = f"{input_file}.temp"
        if os.path.exists(temp_file):
            os.remove(temp_file)
            logger.info(f"ลบไฟล์ชั่วคราว: {temp_file}")
    else:
        final_output_file = output_file
        df.to_csv(final_output_file, index=False, encoding='utf-8')
        logger.info(f"บันทึกข้อมูลสุดท้ายที่: {final_output_file}")
        
        # ลบไฟล์ชั่วคราว
        import os
        temp_file = f"{output_file}.temp"
        if os.path.exists(temp_file):
            os.remove(temp_file)
            logger.info(f"ลบไฟล์ชั่วคราว: {temp_file}")
    
    # สรุปผลลัพธ์ (เฉพาะแถวที่ประมวลผลในครั้งนี้)
    processed_df = df.iloc[start_row:end_row]
    success_count = processed_df['geocoding_status'].value_counts().get('OK', 0)
    error_count = processed_df['geocoding_status'].isna().sum() + (processed_df['geocoding_status'] == 'ERROR').sum()
    
    logger.info(f"สรุปผลลัพธ์ (แถว {start_row+1}-{end_row}):")
    logger.info(f"- ประมวลผลจริง: {processed_count} แถว")
    logger.info(f"- ประสบความสำเร็จ: {success_count} แถว")
    logger.info(f"- เกิดข้อผิดพลาด: {error_count} แถว")
    if processed_count > 0:
        logger.info(f"- อัตราความสำเร็จ: {(success_count/processed_count)*100:.2f}%")

def check_file_status(file_path: str) -> Dict:
    """
    ตรวจสอบสถานะของไฟล์และข้อมูล geocoding
    
    Args:
        file_path (str): 路径ไฟล์ CSV
        
    Returns:
        Dict: ข้อมูลสถานะของไฟล์
    """
    try:
        df = pd.read_csv(file_path)
        total_rows = len(df)
        
        # ตรวจสอบคอลัมน์ geocoding
        has_geocoding = 'latitude' in df.columns and 'longitude' in df.columns
        
        if has_geocoding:
            completed_rows = df[df['latitude'].notna() & df['longitude'].notna()].shape[0]
            error_rows = df[df['geocoding_status'] == 'ERROR'].shape[0]
            pending_rows = total_rows - completed_rows - error_rows
        else:
            completed_rows = 0
            error_rows = 0
            pending_rows = total_rows
        
        return {
            'total_rows': total_rows,
            'completed_rows': completed_rows,
            'error_rows': error_rows,
            'pending_rows': pending_rows,
            'has_geocoding': has_geocoding,
            'completion_rate': (completed_rows / total_rows * 100) if total_rows > 0 else 0
        }
    except Exception as e:
        logger.error(f"ไม่สามารถอ่านไฟล์ {file_path}: {e}")
        return None

def main():
    """
    ฟังก์ชันหลัก
    """
    # ตั้งค่า API Key (กรุณาใส่ API Key ของคุณที่นี่)
    API_KEY = "YOUR-KEY"
    
    # ตั้งค่าไฟล์
    INPUT_FILE = "station66_distinct.csv"  # ไฟล์ข้อมูลสถานี
    OUTPUT_FILE = "station66_geocoded.csv"  # ไฟล์ผลลัพธ์
    
    # ตรวจสอบ API Key
    if API_KEY == "YOUR_GOOGLE_MAPS_API_KEY_HERE":
        print("⚠️  กรุณาใส่ Google Maps API Key ในตัวแปร API_KEY")
        print("📝 วิธีได้ API Key:")
        print("   1. ไปที่ Google Cloud Console")
        print("   2. สร้างโปรเจคใหม่หรือเลือกโปรเจคที่มีอยู่")
        print("   3. เปิดใช้งาน Geocoding API")
        print("   4. สร้าง API Key")
        return
    
    # ตรวจสอบสถานะไฟล์
    print("📊 ตรวจสอบสถานะไฟล์...")
    status = check_file_status(INPUT_FILE)
    if status:
        print(f"📈 สถานะไฟล์ {INPUT_FILE}:")
        print(f"   - จำนวนแถวทั้งหมด: {status['total_rows']:,}")
        print(f"   - เสร็จสิ้นแล้ว: {status['completed_rows']:,} ({status['completion_rate']:.1f}%)")
        print(f"   - เกิดข้อผิดพลาด: {status['error_rows']:,}")
        print(f"   - รอดำเนินการ: {status['pending_rows']:,}")
        
        if status['has_geocoding'] and status['pending_rows'] == 0:
            print("✅ ข้อมูล geocoding เสร็จสมบูรณ์แล้ว!")
            return
    
    # ตั้งค่าพารามิเตอร์การประมวลผล
    try:
        # ตัวอย่างการใช้งาน - สามารถปรับค่าเหล่านี้ได้
        START_ROW = 6001         # แถวเริ่มต้น (0-based)
        END_ROW = 9000          # แถวสิ้นสุด (None = จนถึงแถวสุดท้าย)
        BATCH_SIZE = 10        # จำนวนแถวต่อครั้ง
        DELAY = 0.2           # หน่วงเวลาระหว่าง API calls (วินาที)
        INSERT_MODE = True     # True = insert ในไฟล์เดิม, False = สร้างไฟล์ใหม่
        
        print(f"\n🚀 เริ่มประมวลผล:")
        print(f"   - แถว: {START_ROW+1}-{END_ROW if END_ROW else 'สุดท้าย'}")
        print(f"   - Batch size: {BATCH_SIZE}")
        print(f"   - Delay: {DELAY} วินาที")
        print(f"   - Mode: {'Insert ในไฟล์เดิม' if INSERT_MODE else 'สร้างไฟล์ใหม่'}")
        
        # เริ่มประมวลผล
        process_station_data(
            input_file=INPUT_FILE,
            output_file=OUTPUT_FILE,
            api_key=API_KEY,
            batch_size=BATCH_SIZE,
            delay=DELAY,
            start_row=START_ROW,
            end_row=END_ROW,
            insert_mode=INSERT_MODE
        )
        
        final_file = INPUT_FILE if INSERT_MODE else OUTPUT_FILE
        print(f"\n✅ ประมวลผลเสร็จสิ้น! ข้อมูลถูกบันทึกที่: {final_file}")
        
        # แสดงสถานะหลังประมวลผล
        print("\n📊 สถานะไฟล์หลังประมวลผล:")
        final_status = check_file_status(final_file)
        if final_status:
            print(f"   - เสร็จสิ้นแล้ว: {final_status['completed_rows']:,} ({final_status['completion_rate']:.1f}%)")
            print(f"   - เกิดข้อผิดพลาด: {final_status['error_rows']:,}")
            print(f"   - รอดำเนินการ: {final_status['pending_rows']:,}")
        
    except FileNotFoundError:
        print(f"❌ ไม่พบไฟล์: {INPUT_FILE}")
    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    main()
