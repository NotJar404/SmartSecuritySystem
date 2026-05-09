using Microsoft.EntityFrameworkCore;
using SmartSecuritySystem.Models;
using WebApp.Models;

namespace WebApp.Data
{
    public class AppDbContext : DbContext
    {
        public AppDbContext(DbContextOptions<AppDbContext> options)
            : base(options)
        {
        }

        // =========================
        // DBSets
        // =========================
        public DbSet<User> Users { get; set; }
        public DbSet<AuthorizedPersonnel> AuthorizedPersonnel { get; set; }
        public DbSet<LoginLog> LoginLogs { get; set; }
        public DbSet<Room> Rooms { get; set; }
        public DbSet<Camera> CameraDevices { get; set; }
        public DbSet<Alert> Alerts { get; set; }
        public DbSet<AlarmSetting> AlarmSettings { get; set; }
        public DbSet<AccessLog> AccessLogs { get; set; }
        public DbSet<DetectionLog> DetectionLogs { get; set; }
        public DbSet<RoomOccupancy> RoomOccupancy { get; set; }
        public DbSet<Notification> Notifications { get; set; }
        public DbSet<OccupancySession> OccupancySessions { get; set; }
        public DbSet<Recording> Recordings { get; set; }

        // =========================
        // CONFIGURATION
        // =========================
        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);

            // =========================
            // USERS
            // =========================
            modelBuilder.Entity<User>()
                .ToTable("users");

            // =========================
            // AUTHORIZED PERSONNEL
            // =========================
            modelBuilder.Entity<AuthorizedPersonnel>()
                .ToTable("authorized_personnel")
                .HasKey(ap => ap.PersonId);

            // =========================
            // ROOMS
            // =========================
            modelBuilder.Entity<Room>()
                .ToTable("rooms");

            // =========================
            // CAMERAS
            // =========================
            modelBuilder.Entity<Camera>()
                .ToTable("camera_devices");

            modelBuilder.Entity<Camera>()
                .Property(c => c.Status)
                .HasDefaultValue("active");

            // =========================
            // ALERTS (FIXED + ROOM RELATIONSHIP)
            // Custom converters to handle DB values with spaces like 'Brute Force Attempt'
            // =========================
            modelBuilder.Entity<Alert>()
                .ToTable("alerts");

            modelBuilder.Entity<Alert>()
                .Property(a => a.Type)
                .HasConversion(
                    v => v.ToString(),
                    v => ParseAlertTypeFromDb(v)
                );

            modelBuilder.Entity<Alert>()
                .Property(a => a.Severity)
                .HasConversion(
                    v => v.ToString(),
                    v => ParseSeverityFromDb(v)
                );

            modelBuilder.Entity<Alert>()
                .Property(a => a.Status)
                .HasConversion<string>()
                .HasDefaultValue(AlertStatus.New)
                .IsRequired();

            // 🔥 IMPORTANT: Alert → Room relationship
            modelBuilder.Entity<Alert>()
                .HasOne(a => a.Room)
                .WithMany()
                .HasForeignKey(a => a.RoomId)
                .OnDelete(DeleteBehavior.SetNull);

            // =========================
            // ALARM SETTINGS
            // =========================
            modelBuilder.Entity<AlarmSetting>()
                .ToTable("alarm_settings");

            // =========================
            // ACCESS LOGS
            // =========================
            modelBuilder.Entity<AccessLog>()
                .ToTable("access_logs");

            // =========================
            // DETECTION LOGS
            // =========================
            modelBuilder.Entity<DetectionLog>()
                .ToTable("detection_logs");

            // =========================
            // ROOM OCCUPANCY
            // =========================
            modelBuilder.Entity<RoomOccupancy>()
                .ToTable("room_occupancy");

            // =========================
            // OCCUPANCY SESSIONS (FSM STATE TRACKING)
            // =========================
            modelBuilder.Entity<OccupancySession>()
                .ToTable("occupancy_sessions");

            modelBuilder.Entity<OccupancySession>()
                .HasIndex(s => s.SessionId)
                .IsUnique();

            modelBuilder.Entity<OccupancySession>()
                .HasOne(s => s.Person)
                .WithMany()
                .HasForeignKey(s => s.PersonId)
                .OnDelete(DeleteBehavior.SetNull);

            modelBuilder.Entity<OccupancySession>()
                .HasOne(s => s.Room)
                .WithMany()
                .HasForeignKey(s => s.RoomId)
                .OnDelete(DeleteBehavior.SetNull);

            // =========================
            // LOGIN LOGS
            // =========================
            modelBuilder.Entity<LoginLog>()
                .ToTable("login_logs");

            // =========================
            // NOTIFICATIONS
            // =========================
            modelBuilder.Entity<Notification>()
                .ToTable("notifications");

            modelBuilder.Entity<Notification>()
                .Property(n => n.IsRead)
                .HasDefaultValue(false);

            modelBuilder.Entity<Notification>()
                .Property(n => n.Timestamp)
                .HasDefaultValueSql("CURRENT_TIMESTAMP");

            modelBuilder.Entity<Notification>()
                .Property(n => n.TargetRole)
                .HasMaxLength(50);

            // =========================
            // RECORDINGS (VIDEO EVIDENCE)
            // =========================
            modelBuilder.Entity<Recording>()
                .ToTable("recordings");

            modelBuilder.Entity<Recording>()
                .HasOne(r => r.Alert)
                .WithMany()
                .HasForeignKey(r => r.AlertId)
                .OnDelete(DeleteBehavior.Cascade);

            modelBuilder.Entity<Recording>()
                .HasOne(r => r.Camera)
                .WithMany()
                .HasForeignKey(r => r.CameraId)
                .OnDelete(DeleteBehavior.Cascade);
        }

        // =========================
        // DB STRING → ENUM PARSERS (handles spaces, mixed case)
        // =========================
        private static AlertType ParseAlertTypeFromDb(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return AlertType.SuspiciousActivity;

            // Try direct parse first (e.g. "Intrusion")
            if (Enum.TryParse<AlertType>(value, true, out var result))
                return result;

            // Strip spaces and try again (e.g. "Brute Force Attempt" → "BruteForceAttempt")
            var stripped = value.Replace(" ", "").Replace("-", "").Replace("_", "");
            if (Enum.TryParse<AlertType>(stripped, true, out var result2))
                return result2;

            // Fallback
            return AlertType.SuspiciousActivity;
        }

        private static SeverityLevel ParseSeverityFromDb(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return SeverityLevel.WARNING;

            // Map legacy database values to enum values
            var normalized = value.Trim().ToUpper();
            if (normalized == "HIGH") return SeverityLevel.CRITICAL;
            if (normalized == "LOW") return SeverityLevel.INFO;

            if (Enum.TryParse<SeverityLevel>(value, true, out var result))
                return result;

            var stripped = value.Replace(" ", "").Replace("-", "").Replace("_", "");
            if (Enum.TryParse<SeverityLevel>(stripped, true, out var result2))
                return result2;

            return SeverityLevel.WARNING;
        }
    }
}