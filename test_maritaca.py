#!/usr/bin/env python3
"""
Test script for Maritaca AI integration
"""

import os
import sys
from pathlib import Path

# Add current directory to path to import processor functions
sys.path.insert(0, str(Path(__file__).parent))

from processor import _get_api_provider, _call_maritaca_pairs, _call_maritaca_translate_to_zht

def test_api_provider_selection():
    """Test API provider selection logic"""
    print("Testing API provider selection...")
    
    # Clear environment variables
    if 'MARITACA_API_KEY' in os.environ:
        del os.environ['MARITACA_API_KEY']
    if 'DEEPSEEK_API_KEY' in os.environ:
        del os.environ['DEEPSEEK_API_KEY']
    
    try:
        provider = _get_api_provider()
        print(f"❌ Expected error but got provider: {provider}")
        return False
    except RuntimeError as e:
        print(f"✅ Correctly raised error: {e}")
    
    # Test with Maritaca key
    os.environ['MARITACA_API_KEY'] = 'test_key'
    provider = _get_api_provider()
    if provider == 'maritaca':
        print("✅ Correctly selected Maritaca AI")
    else:
        print(f"❌ Expected 'maritaca' but got: {provider}")
        return False
    
    # Test with DeepSeek key (should still prefer Maritaca)
    os.environ['DEEPSEEK_API_KEY'] = 'test_deepseek_key'
    provider = _get_api_provider()
    if provider == 'maritaca':
        print("✅ Correctly prioritized Maritaca AI over DeepSeek")
    else:
        print(f"❌ Expected 'maritaca' but got: {provider}")
        return False
    
    # Test with only DeepSeek key
    del os.environ['MARITACA_API_KEY']
    provider = _get_api_provider()
    if provider == 'deepseek':
        print("✅ Correctly selected DeepSeek as fallback")
    else:
        print(f"❌ Expected 'deepseek' but got: {provider}")
        return False
    
    return True

def test_maritaca_functions():
    """Test Maritaca AI functions (without actual API calls)"""
    print("\nTesting Maritaca AI functions...")
    
    # Test with invalid API key (should fail gracefully)
    os.environ['MARITACA_API_KEY'] = 'invalid_key'
    
    try:
        result = _call_maritaca_pairs("测试文本")
        print(f"❌ Expected error but got result: {result}")
        return False
    except Exception as e:
        print(f"✅ Correctly handled error in pairs function: {type(e).__name__}")
    
    try:
        result = _call_maritaca_translate_to_zht("Hello world", "eng")
        print(f"❌ Expected error but got result: {result}")
        return False
    except Exception as e:
        print(f"✅ Correctly handled error in translate function: {type(e).__name__}")
    
    return True

def main():
    """Run all tests"""
    print("🧪 Testing Maritaca AI Integration\n")
    
    success = True
    
    # Test API provider selection
    if not test_api_provider_selection():
        success = False
    
    # Test Maritaca functions
    if not test_maritaca_functions():
        success = False
    
    if success:
        print("\n✅ All tests passed! Maritaca AI integration is working correctly.")
        print("\nTo use Maritaca AI:")
        print("1. Set MARITACA_API_KEY environment variable")
        print("2. Run: python3 processor.py <directory>")
    else:
        print("\n❌ Some tests failed. Check the implementation.")
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
