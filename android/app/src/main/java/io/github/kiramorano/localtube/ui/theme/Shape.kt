package io.github.kiramorano.localtube.ui.theme

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

/**
 * Скругления. Ступени те же, что в вебе (--lt-radius-* из static/css/ui.css).
 *
 * До этого радиусы задавались числами по месту, и в интерфейсе одновременно
 * жили 4, 8, 10 и 12dp — заметнее всего на соседних элементах: карточка со
 * скруглением 12dp, а меню внутри неё — 10dp.
 */
object LtRadius {
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    /** Пилюля: для чипов и круглых кнопок. */
    val pill = 999.dp
}

/**
 * Отступы. --lt-space-* из веб-версии.
 *
 * Шаг в 4dp совпадает с сеткой Material, так что значения не приходится
 * пересчитывать под каждую платформу.
 */
object LtSpace {
    val x1 = 4.dp
    val x2 = 8.dp
    val x3 = 12.dp
    val x4 = 16.dp
    val x5 = 20.dp
    val x6 = 24.dp
    val x8 = 32.dp
}

/**
 * Минимальная площадь под палец.
 *
 * Material требует 48dp, и в отличие от веба (там порог 44px из рекомендаций
 * Apple) занижать это значение незачем: `IconButton` по умолчанию уже 48dp, а
 * вручную заданные размеры вроде `.size(32.dp)` его как раз ломают.
 */
object LtTap {
    val min = 48.dp
    /** Видимый кружок внутри области нажатия: сама область остаётся 48dp. */
    val visual = 36.dp
}

val LtShapes = Shapes(
    extraSmall = RoundedCornerShape(LtRadius.sm),
    small = RoundedCornerShape(LtRadius.sm),
    medium = RoundedCornerShape(LtRadius.md),
    large = RoundedCornerShape(LtRadius.lg),
    extraLarge = RoundedCornerShape(LtRadius.lg)
)
