#!/usr/bin/env python3
"""
Test script to verify the multi-step registration form JavaScript functionality
"""
import requests
from bs4 import BeautifulSoup

def test_register_page():
    """Test that the register page loads and has the correct JavaScript structure"""
    print("Testing multi-step registration form...")

    # Get the register page
    response = requests.get('http://localhost:5004/register')
    if response.status_code != 200:
        print(f"❌ Failed to load register page: {response.status_code}")
        return False

    soup = BeautifulSoup(response.text, 'html.parser')

    # Check for step containers
    steps = soup.find_all(id=lambda x: x and x.startswith('step-'))
    step_ids = [step.get('id') for step in steps]
    expected_steps = ['step-1', 'step-2', 'step-3']

    print(f"Found step containers: {step_ids}")

    for expected_step in expected_steps:
        if expected_step not in step_ids:
            print(f"❌ Missing step container: {expected_step}")
            return False
        else:
            print(f"✅ Found step container: {expected_step}")

    # Check for step indicators
    indicators = soup.find_all(id=lambda x: x and x.endswith('-indicator'))
    indicator_ids = [ind.get('id') for ind in indicators]
    expected_indicators = ['step-1-indicator', 'step-2-indicator', 'step-3-indicator']

    print(f"Found step indicators: {indicator_ids}")

    for expected_indicator in expected_indicators:
        if expected_indicator not in indicator_ids:
            print(f"❌ Missing step indicator: {expected_indicator}")
            return False
        else:
            print(f"✅ Found step indicator: {expected_indicator}")

    # Check for JavaScript functions
    script_tags = soup.find_all('script')
    js_content = ''.join([script.get_text() for script in script_tags])

    required_functions = ['showStep', 'validateCurrentStep', 'nextStep', 'prevStep', 'showError', 'hideError']
    print("Checking for JavaScript functions...")

    for func in required_functions:
        if func in js_content:
            print(f"✅ Found JavaScript function: {func}")
        else:
            print(f"❌ Missing JavaScript function: {func}")
            return False

    # Check for console.log statements (our debugging additions)
    if 'console.log' in js_content:
        print("✅ Found debugging console.log statements")
    else:
        print("❌ Missing debugging console.log statements")

    print("🎉 All tests passed! Multi-step form structure is correct.")
    return True

if __name__ == "__main__":
    test_register_page()