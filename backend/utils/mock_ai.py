import asyncio
import json


async def completion(role):
    await asyncio.sleep(2)
    responses = {
        'analyzer': {'clean_problem': 'Mock plumbing check', 'constraints': {}, 'dsa_category': 'Arrays', 'dsa_subcategory': 'Test', 'sample_inputs': [], 'sample_outputs': [], 'edge_cases': [], 'difficulty': 'Easy'},
        'strategist': {'reasoning_chain': 'Test fixture', 'chosen_approach': 'Mock', 'approach_description': 'Test only', 'time_complexity': 'O(1)', 'space_complexity': 'O(1)', 'alternate_approaches': [], 'implementation_hints': [], 'new_semantic_pattern': ''},
        'coder': 'def solve():\n    return [0, 1]',
        'reviewer': {'verdict': 'APPROVE', 'issues': [], 'confidence': 'HIGH'},
    }
    result = responses[role]
    return (result if isinstance(result, str) else json.dumps(result)), 'mock'
