import json
import time
from faculty_matcher import process_faculty_member

new_faculty_batch = [
    "Тимофій Брік",
    "Максим Обрізан",
    "Володимир Кулик",
    "Іван Гомза",
    "Ігор Сердюк",
    "Сергій Кандул",
    "Олена Бєсєдіна",
    "Наталія Шаповал",
    "Вероніка Юрчук",
    "Олена Галицька",
    "Роман Міщенко",
    "Тетяна Прощенко",
    "Юрій Чоп'юк",
    "Володимир Скочко",
    "Сергій Яковлєв"
]

def main():
    print("=" * 70)
    print(f"RUNNING BENCHMARK FOR {len(new_faculty_batch)} NEW KSE FACULTY MEMBERS")
    print("=" * 70)

    results = []
    for i, name in enumerate(new_faculty_batch, 1):
        print(f"\n[{i}/{len(new_faculty_batch)}] Processing: {name}")
        try:
            res = process_faculty_member(name)
            results.append(res)
        except Exception as e:
            print(f"  [ERROR processing {name}]: {e}")
            results.append({
                'input_name': name,
                'status': 'ERROR',
                'error': str(e)
            })
        time.sleep(1)  # Polite sleep

    output_path = 'faculty_results_batch2.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"COMPLETED! Results written to {output_path}")
    print("=" * 70)

if __name__ == '__main__':
    main()
